'''
Client that consumes images to be processed by the Caffe framework.

Author: Axel.Tidemann@telenor.com
'''

import argparse
from collections import namedtuple
import cStringIO as StringIO
import logging
import cPickle as pickle

import requests
import matplotlib
matplotlib.use('Agg')
import caffe
import redis

from app import ImagenetClassifier

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument(
    '-s', '--server',
    help='the redis server address',
    default='localhost')
parser.add_argument(
    '-p', '--port',
    help='the redis port',
    default='6379')
parser.add_argument(
    '-q', '--queue',
    help='redis queue to read from',
    default='classify')
args = parser.parse_args()

logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%Y-%m-%d %I:%M:%S')

ImagenetClassifier.default_args.update({'gpu_mode': True})
model = ImagenetClassifier(**ImagenetClassifier.default_args)
model.net.forward()

Task = namedtuple('Task', 'queue value')
Result = namedtuple('Result', 'OK maximally_accurate maximally_specific computation_time')

r_server = redis.StrictRedis(args.server, args.port)
r_server.config_set('notify-keyspace-events', 'Kh')

while True:
    task = Task(*r_server.brpop(args.queue))
    specs = pickle.loads(task.value)
    specs = namedtuple('Specs', specs.keys())(**specs)
    logging.info(specs)
    result_key = 'prediction:{}:{}'.format(specs.user, specs.path)

    try:
        response = requests.get(specs.path, timeout=10)
        string_buffer = StringIO.StringIO(response.content)
        image = caffe.io.load_image(string_buffer)

        result = Result(*model.classify_image(image))
        
        r_server.hmset(result_key, result._asdict())
        r_server.zadd('prediction:{}:category:{}'.format(specs.user, result.maximally_specific[0][0]),
                      result.maximally_specific[0][1], specs.path)

    except:
        logging.error('Something went wrong when classifying the image.')
        r_server.hmset(result_key, {'OK': 'False'})
