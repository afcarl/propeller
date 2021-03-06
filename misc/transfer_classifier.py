# Copyright 2016 Telenor ASA, Author: Axel Tidemann, Cyril Banino-Rokkones
# The software includes elements of example code. Copyright 2015 Google, Inc. Licensed under Apache License, Version 2.0.
# https://www.tensorflow.org/versions/r0.7/tutorials/image_recognition/index.html

import os.path
import re
import sys
import tarfile
import cStringIO as StringIO
import logging
import cPickle as pickle
import os
import time
import glob
import json
from collections import namedtuple
import tempfile
from contextlib import contextmanager
import time
import math

import tensorflow.python.platform
import numpy as np
import tensorflow as tf
import redis
import requests
from wand.image import Image
from ast import literal_eval as make_tuple
from tensorflow.python.platform import gfile
import blosc

from aqbc_utils import hash_bottlenecks
from utils import load_graph, maybe_download_and_extract

parser = argparse.ArgumentParser(description='''Listens to a redis list, downloads
the image and feeds it to the Inception model. Uses the next-to-last layer output as input
to a classifier.''', formatter_class=argparse.ArgumentDefaultsHelpFormatter)

parser.add_argument(
      'classifier',
      help='Path to the transfer learned model')
parser.add_argument(
      'mapping',
      help='Path to a mapping from node IDs to readable text')
parser.add_argument(
      '--model_dir',
      help='Path to Inception model, will be downloaded if not present.',
      default='/tmp/imagenet')
parser.add_argument(
      '--num_top_predictions',
      help='Display this many predictions.',
      type=int,
      default=5)
parser.add_argument(
      '--redis_server',
      default='localhost')
parser.add_argument(
      '--redis_port',
      type=int,
      default=6379)
parser.add_argument(
      '--redis_queue',
      help='Redis queue to read images from',
      default='classify')
parser.add_argument(
    '--mem_ratio',
    help='Ratio of memory to reserve on the GPU instance',
    type=float,
    default=.95)
args = parser.parse_args()

Task = namedtuple('Task', 'queue value')
Specs = namedtuple('Specs', 'group path res_q')
Result = namedtuple('Result', 'OK predictions computation_time path')

logging.getLogger().setLevel(logging.INFO)

@contextmanager
def convert_to_jpg(data):
    tmp = tempfile.NamedTemporaryFile(delete=False)

    with Image(file=StringIO.StringIO(data)) as img:
        if img.format != 'JPEG':
            logging.info('Converting {} to JPEG.'.format(img.format))
            img.format = 'JPEG'
            img.save(tmp)

    tmp.close()
    yield tmp.name
    os.remove(tmp.name)

        
def classify_images(mapping):
    gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=args.mem_ratio)
    with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options)) as sess:
        load_graph(os.path.join(args.model_dir, 'classify_image_graph_def.pb'))
        inception_next_last_layer = sess.graph.get_tensor_by_name('pool_3:0')

        load_graph(args.classifier)
        transfer_predictor = sess.graph.get_tensor_by_name('output:0')

        r_server = redis.StrictRedis(args.redis_server, args.redis_port)

        if args.hashing:
            R_c = r_server.get('hashing:R')
            if R_c == None:
                logging.info('Did not find any Rotation matrix in redis at key: <hashing:R>. Continuing without hashing.')
                args.hashing = False
            else:
                R_u = blosc.decompress(R_c)
                R = np.fromstring(R_u, dtype=np.float64)
                bits = R.shape[0]/2048
                R = R.reshape(2048, bits)
                R = np.transpose(R)

        while True:
            task = Task(*r_server.brpop(args.redis_queue))
            specs = Specs(**pickle.loads(task.value))
            logging.info(specs)
            result_key = 'archive:{}:{}'.format(specs.group, specs.path)
            try:
                response = requests.get(specs.path, timeout=10)
                with convert_to_jpg(response.content) as jpg:
                    image_data = gfile.FastGFile(jpg).read()

                starttime = time.time()
                hidden_layer = sess.run(inception_next_last_layer,
                                        {'DecodeJpeg/contents:0': image_data})

                predictions = sess.run(transfer_predictor, {'input:0': np.atleast_2d(np.squeeze(hidden_layer)) })
                predictions = np.squeeze(predictions)
                top_k = predictions.argsort()[-args.num_top_predictions:][::-1]

                endtime = time.time()

                result = Result(True,
                                [ (mapping[str(node_id)], predictions[node_id]) for node_id in top_k ],
                                endtime - starttime,
                                specs.path)

                value = result._asdict()

                hidden_layer = hidden_layer.reshape(2048,1)
                h_s_packed = blosc.compress(hidden_layer.tostring(), typesize=8, cname='zlib')
                
                if args.hashing:
                    _, c = hash_bottlenecks(R, hidden_layer)
                    r_server.hmset("hashing:codes:" + c[0].bin, {result_key: h_s_packed} )
                    value['hash'] = c[0].bin

                r_server.hmset(result_key, value)

                # for demo
                last_key = 'archive:{}:{}'.format(specs.group, 'lastprediction')
                r_server.hmset(last_key, result._asdict())

                r_server.hset('archive:{}:category:{}'.format(specs.group, result.predictions[0][0]),
                              specs.path, h_s_packed)

                # push result on result queue
                preds = {}
                for node_id in top_k:
                    preds[str(mapping[str(node_id)])] = str(predictions[node_id])

                json_blob = {
                    'predictions':preds,
                    'path':specs.path,
                    'hidden_states':h_s_packed
                }

                if specs.res_q != "":
                    r_server.rpush(specs.res_q, json.dumps(json_blob, ensure_ascii=False, encoding="utf-8"))

                logging.info(result)
            except Exception as e:
                print "exception*****************", e
                logging.error('Something went wrong when classifying the image: {}'.format(e))
                  r_server.hmset(result_key, {'OK': False})

def send_kaidee_data(r_server, specs, result):

    # create redis key from image path
    full_url = specs.path.split('//')
    url_path = len(full_url)>1 and full_url[1] or full_url[0]
    kaidee_result_key = url_path.split('/', 1)[1]

    # Set to result to Redis with key from image path
    r_server.hmset(kaidee_result_key, result._asdict())

    # Publish predictions result to classify channel via Redis PubSub
    predictions_dict = dict((x, y) for x, y in result.predictions)
    r_server.publish('classify', pickle.dumps({'path': specs.path, 'group': specs.group,
                                             'predictions': predictions_dict}))


if __name__ == '__main__':
    maybe_download_and_extract(args.model_dir)
    with open(args.mapping) as f:
        mapping = json.load(f)

    classify_images(mapping)
