# Copyright 2016 Telenor ASA, Author: Axel Tidemann
# The software includes elements of example code. Copyright 2015 Google, Inc. Licensed under Apache License, Version 2.0.
# https://github.com/tensorflow/tensorflow/tree/master/tensorflow/examples/tutorials/mnist

'''
Trains the final layer of the Inception model. You must have
collected the next to last layer states beforehand. For transfer learning,
make sure the batch_size is really big, since the amount of data per sample
is _very_ small compared to when loading images, typically 
2048/(299*299*3) = 0.8%

Author: Axel.Tidemann@telenor.com
'''

import argparse
import os

import numpy as np
import tensorflow as tf
from tensorflow.python.client import graph_util
from tensorflow.python.platform import gfile

from training_data import read_data

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument(
    'data_folder',
    help='Folder with Inception states for training')
parser.add_argument(
    '--train_ratio',
    help='Train ratio',
    type=float,
    default=.8)
parser.add_argument(
    '--validation_ratio',
    help='Validation ratio',
    type=float,
    default=.1)
parser.add_argument(
    '--test_ratio',
    help='Test ratio',
    type=float,
    default=.1)
parser.add_argument(
    '--save_every',
    help='How often (in epochs) to save checkpoints',
    type=int,
    default=10)
parser.add_argument(
    '--checkpoint_dir',
    help='Where to save the checkpoints',
    default='cv/')
parser.add_argument(
    '--batch_size',
    help='Batch size for training',
    type=int,
    default=1024)
parser.add_argument(
    '--epochs',
    help='Maximum number of epochs before ending the training',
    type=int,
    default=10000)
parser.add_argument(
    '--print_every',
    help='Print training and validation accuracy every X steps',
    type=int,
    default=100)
parser.add_argument(
    '--model_dir',
    help='Where to save the transfer learned model',
    default='.')
args = parser.parse_args()

assert args.train_ratio + args.validation_ratio + args.test_ratio == 1, 'Train/validation/test ratios must sum up to 1'

data = read_data(args.data_folder, args.train_ratio, args.validation_ratio, args.test_ratio)

if not os.path.exists(args.checkpoint_dir):
    os.makedirs(args.checkpoint_dir)

def weight_variable(shape, name):
    initial = tf.truncated_normal(shape, stddev=0.1)
    return tf.Variable(initial,name=name)

def bias_variable(shape, name):
    initial = tf.constant(0.1, shape=shape)
    return tf.Variable(initial,name=name)

with tf.Session() as sess:
    x = tf.placeholder("float", shape=[None, data.train.X_features], name='input')
    y_ = tf.placeholder("float", shape=[None, data.train.Y_features], name='target')

    W = weight_variable([data.train.X_features,data.train.Y_features], name='weights')
    b = bias_variable([data.train.Y_features], name='bias')

    y = tf.nn.softmax(tf.matmul(x,W) + b, name='output')
    cross_entropy = -tf.reduce_sum(y_*tf.log(y))

    train_step = tf.train.AdamOptimizer(1e-4).minimize(cross_entropy)
    correct_prediction = tf.equal(tf.argmax(y,1), tf.argmax(y_,1))
    accuracy = tf.reduce_mean(tf.cast(correct_prediction, "float"))

    saver = tf.train.Saver()
    
    sess.run(tf.initialize_all_variables())

    last_i = 0
    while data.train.epoch < args.epochs:
        i = data.train.epoch
        
        batch_x, batch_y = data.train.next_batch(args.batch_size)
        train_step.run(feed_dict={x: batch_x, y_: batch_y})

        if (i + 1) % args.save_every == 0:
            saver.save(sess, args.checkpoint_dir + 'model.ckpt',
                       global_step=i+1)

        if i % args.print_every == 0 and last_i != i:
            train_accuracy = accuracy.eval(feed_dict={
                x:batch_x, y_: batch_y})

            batch_x, batch_y = data.validation.next_batch(args.batch_size)

            validation_accuracy = accuracy.eval(feed_dict={
                x:batch_x, y_: batch_y})
            print 'Epoch {} train accuracy: {}, validation accuracy: {}'.format(i, train_accuracy, validation_accuracy)
            last_i = i


    output_graph_def = graph_util.convert_variables_to_constants(
        sess, sess.graph.as_graph_def(), ['input', 'output'])

    model_name = 'transfer_classifier_epochs_{}_batch_{}_train_ratio_{}.pb'.format(args.epochs, args.batch_size, args.train_ratio)
    with gfile.FastGFile(os.path.join(args.model_dir, model_name), 'w') as f:
        f.write(output_graph_def.SerializeToString())

    print 'Trained model saved to {}'.format(os.path.join(args.model_dir, model_name))

    if args.test_ratio > 0:
        test_accuracy = accuracy.eval(feed_dict={x: data.test.X, y_: data.test.Y})
        print 'Evaluation on testing data: {}'.format(test_accuracy)
