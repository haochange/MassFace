"""Training a face recognizer with TensorFlow based on the FaceNet paper
FaceNet: A Unified Embedding for Face Recognition and Clustering: http://arxiv.org/abs/1503.03832
"""
# MIT License
# 
# Copyright (c) 2016 David Sandberg
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import os.path
import os
import time
import sys
#sys.path.insert(0,'../face_reg/lib')
CURRENT_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,CURRENT_PATH+'/../lib')
#sys.path.insert(0,'../face_reg/lib/loss')
#import triplet
sys.path.insert(0,CURRENT_PATH+'/../networks')
import utils
import math
import tensorflow as tf
from tensorflow.python.client import timeline
from tensorflow.contrib import slim
from tensorflow.contrib.slim.nets import resnet_v1, resnet_v2
import MobileFaceNet as mobilenet
from tensorflow import data as tf_data
from collections import Counter
import numpy as np
from scipy import misc
import importlib
import itertools
import argparse
#import lfw
import pdb
#import cv2
#import pylab as plt


debug = False
trip_thresh = 0

from tensorflow.python.ops import data_flow_ops

def _from_tensor_slices(tensors_x,tensors_y):
    #return TensorSliceDataset((tensors_x,tensors_y))
    return tf_data.Dataset.from_tensor_slices((tensors_x,tensors_y))



def main(args):
  

    subdir = datetime.strftime(datetime.now(), '%Y%m%d-%H%M%S')
    log_dir = os.path.join(os.path.expanduser(args.logs_base_dir), subdir)
    if not os.path.isdir(log_dir):  # Create the log directory if it doesn't exist
        os.makedirs(log_dir)
    model_dir = os.path.join(os.path.expanduser(args.models_base_dir), subdir)
    if not os.path.isdir(model_dir):  # Create the model directory if it doesn't exist
        os.makedirs(model_dir)

    np.random.seed(seed=args.seed)


    print('load data...')
    if args.dataset == 'webface':
        train_set = utils.get_dataset(args.data_dir)
    elif args.dataset == 'mega':
        train_set = utils.dataset_from_cache(args.data_dir)
    #train_set.extend(ic_train_set)
    print('Loaded dataset: {} persons'.format(len(train_set)))
    def _sample_people(x):
        '''We sample people based on tf.data, where we can use transform and prefetch.

        '''
    
        image_paths, num_per_class = sample_people(train_set,args.people_per_batch*args.num_gpus*args.scale,args.images_per_person)
        labels = []
        for i in range(len(num_per_class)):
            labels.extend([i]*num_per_class[i])
        return (np.array(image_paths),np.array(labels,dtype=np.int32))

    def _parse_function(filename,label):
        file_contents = tf.read_file(filename)

        image = tf.image.decode_image(file_contents, channels=3)
        #image = tf.image.decode_jpeg(file_contents, channels=3)
        #print(image.shape)
        #image.set_shape((args.image_size, args.image_size, 3))
        ''' 
        if args.random_crop:
            print('use random crop')
            image = tf.random_crop(image, [224,224, 3])
            image = tf.image.resize_images(image, size=(args.image_size,args.image_size))
        else:
            print('Not use random crop')
            #image.set_shape((args.image_size, args.image_size, 3))
            image.set_shape((None,None, 3))
            image = tf.image.resize_images(image, size=(args.image_size, args.image_size))
            #print(image.shape)
        '''
        if args.random_flip:
            image = tf.image.random_flip_left_right(image)

        #pylint: disable=no-member
        image.set_shape((args.image_size, args.image_size, 3))
        #image = tf.image.per_image_standardization(image)
        image = tf.cast(image,tf.float32)
        image = tf.subtract(image,127.5)
        image = tf.div(image,128.)
        return image, label

    gpus = range(args.num_gpus)
    
    print('Model directory: %s' % model_dir)
    print('Log directory: %s' % log_dir)
    if args.pretrained_model:
        print('Pre-trained model: %s' % os.path.expanduser(args.pretrained_model))
    
            
    
    with tf.Graph().as_default():
        tf.set_random_seed(args.seed)
        global_step = tf.Variable(0, trainable=False,name='global_step')

        # Placeholder for the learning rate
        learning_rate_placeholder = tf.placeholder(tf.float32, name='learning_rate')
        
        
        phase_train_placeholder = tf.placeholder(tf.bool, name='phase_train')
        
                
        
        #the image is generated by sequence
        with tf.device("/cpu:0"):
            dataset = tf_data.Dataset.range(args.epoch_size*args.max_nrof_epochs*100)
            #dataset.repeat(args.max_nrof_epochs)
            #sample people based map
            dataset = dataset.map(lambda x: tf.py_func(_sample_people,[x],[tf.string,tf.int32]))
            dataset = dataset.flat_map(_from_tensor_slices)
            dataset = dataset.map(_parse_function,num_parallel_calls=8)
            dataset = dataset.batch(args.num_gpus*args.people_per_batch*args.images_per_person)
            iterator = dataset.make_initializable_iterator()
            next_element = iterator.get_next()
            batch_image_split = tf.split(next_element[0],args.num_gpus)
            batch_label = next_element[1]
            
            global trip_thresh
            trip_thresh = args.num_gpus*args.people_per_batch*args.images_per_person * 10
            

    
        
        


        #learning_rate = tf.train.exponential_decay(args.learning_rate, global_step,
        learning_rate = tf.train.exponential_decay(learning_rate_placeholder, global_step,
            args.learning_rate_decay_epochs*args.epoch_size, args.learning_rate_decay_factor, staircase=True)
        tf.summary.scalar('learning_rate', learning_rate)

        opt = utils.get_opt(args.optimizer,learning_rate)
       
        tower_grads = []
        #tower_losses = []
        tower_embeddings = []
        tower_feats = []
        for i in range(len(gpus)):
            with tf.device("/gpu:" + str(gpus[i])):
                with tf.name_scope("tower_" + str(gpus[i])) as scope:
                  with slim.arg_scope([slim.model_variable, slim.variable], device="/cpu:0"):
                    # Build the inference graph
                    #with tf.variable_scope('tower_variable') as var_scope:
                    with tf.variable_scope(tf.get_variable_scope()) as var_scope:
                        reuse = False if i ==0 else True
                        #print('reuse {} in graph {}'.format(reuse,i))
                        if args.network == 'resnet_v2': 
                          with slim.arg_scope(resnet_v2.resnet_arg_scope(args.weight_decay)):
                            #prelogits, end_points = resnet_v1.resnet_v1_50(batch_image_split[i], is_training=phase_train_placeholder, output_stride=16, num_classes=args.embedding_size, reuse=reuse)
                            prelogits, end_points = resnet_v2.resnet_v2_50(batch_image_split[i],is_training=True,
                                        output_stride=16,num_classes=args.embedding_size,reuse=reuse)
                            prelogits = tf.squeeze(prelogits, [1,2], name='SpatialSqueeze')
                        elif args.network == 'resface':
                            prelogits, end_points = resface.inference(batch_image_split[i],1.0,bottleneck_layer_size=args.embedding_size,weight_decay=args.weight_decay,reuse=reuse)
                            print('res face prelogits',prelogits)
                        
                        elif args.network ==  'mobilenet':
                            prelogits, net_points = mobilenet.inference(batch_image_split[i],bottleneck_layer_size=args.embedding_size,phase_train=True,weight_decay=args.weight_decay,reuse=reuse)

                        
                        embeddings = tf.nn.l2_normalize(prelogits, 1, 1e-10, name='embeddings')
                        tf.get_variable_scope().reuse_variables()
                    
                    #embeddings_gather = tf.gather(embeddings,arg_labels)
                    tower_embeddings.append(embeddings)
        embeddings_gather = tf.concat(tower_embeddings,axis=0,name='embeddings_concat')
        
        
        # select triplet pair by tf op
        with tf.name_scope('triplet_part'):
            #embeddings_placeholder = tf.placeholder(tf.float32)
            #labels_placeholder = tf.placeholder(tf.int32)
            #embeddings_norm = tf.nn.l2_normalize(embeddings_placeholder,axis=1)
            embeddings_norm = tf.nn.l2_normalize(embeddings_gather,axis=1)
            distances = utils._pairwise_distances(embeddings_norm,squared=True)
            if args.strategy == 'min_and_min':
                pair = tf.py_func(select_triplets_min_min,[distances,batch_label,args.alpha],tf.int64)
            elif args.strategy == 'min_and_max':
                pair = tf.py_func(select_triplets_min_max,[distances,batch_label,args.alpha],tf.int64)
            elif args.strategy == 'hardest':
                pair = tf.py_func(select_triplets_hardest,[distances,batch_label,args.alpha],tf.int64)
            elif args.strategy == 'batch_random': 
                pair = tf.py_func(select_triplets_batch_random,[distances,batch_label,args.alpha],tf.int64)
            elif args.strategy == 'batch_all': 
                pair = tf.py_func(select_triplets_batch_all,[distances,batch_label,args.alpha],tf.int64)

            else:
                raise ValueError('Not supported strategy {}'.format(args.strategy))
            
            triplet_handle = {}
            triplet_handle['embeddings'] = embeddings_gather
            triplet_handle['labels'] = batch_label
            triplet_handle['pair'] = pair
        if args.mine_method == 'online':
            pair_reshape = tf.reshape(pair,[-1])
            embeddings_gather = tf.gather(embeddings_gather,pair_reshape)
        

        anchor, positive, negative = tf.unstack(tf.reshape(embeddings_gather, [-1,3,args.embedding_size]), 3, 1)
        triplet_loss, pos_d, neg_d = utils.triplet_loss(anchor, positive, negative, args.alpha)
        

        # Calculate the total losses
        regularization_losses = tf.get_collection(tf.GraphKeys.REGULARIZATION_LOSSES)
        triplet_loss = tf.add_n([triplet_loss])
        total_loss = triplet_loss + tf.add_n(regularization_losses)
        #total_loss =  tf.add_n(regularization_losses)
        losses = {}
        losses['triplet_loss'] = triplet_loss
        losses['total_loss'] = total_loss

        update_vars = tf.trainable_variables() 
        with tf.device("/gpu:" + str(gpus[0])):

                    # Build a Graph that trains the model with one batch of examples and updates the model parameters
                    #train_op = facenet.train(total_loss, global_step, args.optimizer, 
                    #    learning_rate, args.moving_average_decay, tf.global_variables())
                    #grads = opt.compute_gradients(total_loss,tf.global_variables())
                    # we use trainable_variables, because the untrainable variable don't have gradient.
                    #grads = opt.compute_gradients(total_loss,tf.trainable_variables(),colocate_gradients_with_ops=True)
                    grads = opt.compute_gradients(total_loss,update_vars,colocate_gradients_with_ops=True)
                    #grads = opt.compute_gradients(total_loss,tf.trainable_variables())
                    tower_grads.append(grads)
                    
        # Create a saver
        #grads = facenet.sum_gradients(tower_grads) 
        apply_gradient_op = opt.apply_gradients(grads,global_step=global_step) 
        #update_ops = [op for op in tf.get_collection(tf.GraphKeys.UPDATE_OPS) if 'pair_part' in op.name] 
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS) 
        print('update ops',update_ops)
        #pdb.set_trace()
        #variable_averages = tf.train.ExponentialMovingAverage(args.moving_average_decay, global_step)
        #variable_averages_op = variable_averages.apply(tf.trainable_variables())
        with tf.control_dependencies(update_ops):
            #train_op_dep = tf.group(apply_gradient_op,variable_averages_op)
            train_op_dep = tf.group(apply_gradient_op)
        #if trilets is empty, then triplet_loss is nan, we prevent it 
        train_op = tf.cond(tf.is_nan(triplet_loss), lambda: tf.no_op('no_train'), lambda: train_op_dep)
         
        save_vars = [var  for var in tf.global_variables() if 'Adagrad' not in var.name and 'global_step' not in var.name ]
        restore_vars = [var  for var in tf.global_variables() if 'Adagrad' not in var.name and 'global_step' not in var.name and 'pair_part' not in var.name]
        #save_vars = [var  for var in tf.trainable_variables() if 'Adagrad' not in var.name and 'global_step' not in var.name]
        saver = tf.train.Saver(save_vars, max_to_keep=3)
        restorer = tf.train.Saver(restore_vars, max_to_keep=3)


        
             

        # Build the summary operation based on the TF collection of Summaries.
        summary_op = tf.summary.merge_all()

        # Start running operations on the Graph.
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=args.gpu_memory_fraction)
        sess = tf.Session(config=tf.ConfigProto(gpu_options=gpu_options,allow_soft_placement=True))        

        # Initialize variables
        sess.run(tf.global_variables_initializer(), feed_dict={phase_train_placeholder:True})
        sess.run(tf.local_variables_initializer(), feed_dict={phase_train_placeholder:True})

        sess.run(iterator.initializer)

        summary_writer = tf.summary.FileWriter(log_dir, sess.graph)
        coord = tf.train.Coordinator()
        tf.train.start_queue_runners(coord=coord, sess=sess)
        
        forward_embeddings = []
        with sess.as_default():

            if args.pretrained_model:
                print('Restoring pretrained model: %s' % args.pretrained_model)
                #restorer.restore(sess, os.path.expanduser(args.pretrained_model))
                saver.restore(sess, os.path.expanduser(args.pretrained_model))

            # Training and validation loop
            epoch = 0
            while epoch < args.max_nrof_epochs:
                step = sess.run(global_step, feed_dict=None)
                epoch = step // args.epoch_size
                if debug:
                    debug_train(args, sess, train_set, epoch, image_batch_gather, enqueue_op,batch_size_placeholder, image_batch_split,image_paths_split,num_per_class_split,
                            image_paths_placeholder,image_paths_split_placeholder, labels_placeholder, labels_batch, num_per_class_placeholder,num_per_class_split_placeholder,len(gpus))
                # Train for one epoch
                if args.mine_method == 'simi_online':
                  train_simi_online(args, sess, epoch, len(gpus),embeddings_gather,batch_label,next_element[0],batch_image_split,learning_rate_placeholder,
                     learning_rate, phase_train_placeholder, global_step, pos_d, neg_d, triplet_handle,
                     losses, train_op, summary_op, summary_writer, args.learning_rate_schedule_file)

                elif args.mine_method == 'online':
                  train_online(args, sess, epoch, 
                     learning_rate, phase_train_placeholder, global_step, 
                     losses, train_op, summary_op, summary_writer, args.learning_rate_schedule_file)
                  
                else:
                  raise ValueError('Not supported mini method {}'.format(args.mine_method))


                # Save variables and the metagraph if it doesn't exist already
                save_variables_and_metagraph(sess, saver, summary_writer, model_dir, subdir, step)

                # Evaluate on LFW
                
    return model_dir


def train_simi_online(args, sess, epoch, num_gpus,embeddings_gather,batch_label,images,batch_image_split, learning_rate_placeholder,
          learning_rate, phase_train_placeholder, global_step, pos_d, neg_d,triplet_handle,
          loss, train_op, summary_op, summary_writer, learning_rate_schedule_file):
    if args.learning_rate>0.0:
        lr = args.learning_rate
    else:
        lr = utils.get_learning_rate_from_file(learning_rate_schedule_file, epoch)
    batch_number = 0
    while batch_number < args.epoch_size:
        # Sample people randomly from the dataset
        #image_paths, num_per_class = sample_people(dataset, args.people_per_batch, args.images_per_person)
        embeddings_list = []
        labels_list = []
        images_list = []
        f_time = time.time()
        for i in range(args.scale):
            #embeddings_np,labels_np,images_np = sess.run([embeddings_gather,batch_label,batch_image_split[0]],feed_dict={phase_train_placeholder:True})
            embeddings_np,labels_np,images_np = sess.run([embeddings_gather,batch_label,images],feed_dict={phase_train_placeholder:False,learning_rate_placeholder:lr})
            #pdb.set_trace()
            embeddings_list.append(embeddings_np)
            labels_list.append(labels_np)
            images_list.append(images_np)
        embeddings_all = np.vstack(embeddings_list)
        labels_all = np.hstack(labels_list)
        images_all = np.vstack(images_list)
        print('forward time: {}'.format(time.time()-f_time))
        f_time = time.time()
        #get triplet pairs by python
        #triplet_pairs = select_triplets_hard(embeddings_all,labels_all,args.alpha)
        #get triplet_pairs by tf op
        triplet_pairs = sess.run(triplet_handle['pair'],feed_dict={triplet_handle['embeddings']: embeddings_all,triplet_handle['labels']: labels_all})
        print('tf op select triplet time: {}'.format(time.time()-f_time))
        #pdb.set_trace()
        triplet_images_size = len(triplet_pairs)
        if args.show_triplet:
            show_images =  (images_all*128.+127.5)/255.
            save_dir = 'rm/{}_{}'.format(epoch,batch_number)
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            for i in range(triplet_images_size//3):
                start_i = i*3
                image_a = show_images[triplet_pairs[start_i]]
                image_p = show_images[triplet_pairs[start_i+1]]
                image_n = show_images[triplet_pairs[start_i+2]]
                image_apn = np.concatenate([image_a,image_p,image_n],axis=1)
                to_name = '{}/{}.jpg'.format(save_dir,i)
                #pdb.set_trace()
                misc.imsave(to_name,image_apn)

        #if triplet_images_size < args.num_gpus*3:
        #    continue
        total_batch_size = args.num_gpus*args.people_per_batch*args.images_per_person
        nrof_batches = int(math.ceil(1.0 * (triplet_images_size//(args.num_gpus*3))*args.num_gpus*3 / total_batch_size))
        if nrof_batches == 0:
            print('continue forward')
            continue
        for i in range(nrof_batches):
            start_index = i*total_batch_size
            end_index = min((i+1)*total_batch_size, (triplet_images_size//(args.num_gpus*3))*args.num_gpus*3)
            #select_triplet_pairs = triplet_pairs[:total_batch_size] if triplet_images_size >= total_batch_size else triplet_pairs[:(triplet_images_size//(args.num_gpus*3))*args.num_gpus*3]
            select_triplet_pairs = triplet_pairs[start_index:end_index]
            select_images = images_all[select_triplet_pairs]
            #print('triplet pairs: {}/{}'.format(len(select_triplet_pairs)//3,triplet_images_size//3))
            print('triplet pairs: {}/{}'.format(end_index//3,triplet_images_size//3))

            start_time = time.time()
            #pdb.set_trace()
            
            print('Running forward pass on sampled images: ', end='')
            #feed_dict = {learning_rate_placeholder: lr, phase_train_placeholder: True}
            #feed_dict = { phase_train_placeholder: True,images: select_images}
            feed_dict = { phase_train_placeholder: False,images: select_images,learning_rate_placeholder:lr}
            start_time = time.time()
            #pdb.set_trace()
            #triplet_err,total_err, _, step, emb, lab = sess.run([loss['triplet_loss'],loss['total_loss'], train_op, global_step, embeddings, labels_batch], feed_dict=feed_dict,options=run_options,run_metadata=run_metadata)
            #triplet_err,total_err, _, step = sess.run([loss['triplet_loss'],loss['total_loss'], train_op, global_step ], feed_dict=feed_dict,options=run_options,run_metadata=run_metadata)
            triplet_err,total_err, _, step,lr,_, pos_np, neg_np = sess.run([loss['triplet_loss'],loss['total_loss'], train_op, global_step, learning_rate, summary_op, pos_d, neg_d], feed_dict=feed_dict)
            duration = time.time() - start_time
            print('Epoch: [%d][%d/%d]\tTime %.3f\tTriplet Loss %2.3f Total Loss %2.3f lr %2.5f, pos_d %2.5f, neg_d %2.5f' %
                      (epoch, batch_number+1, args.epoch_size, duration, triplet_err,total_err,lr, pos_np,neg_np))
            # Add validation loss and accuracy to summary
        summary = tf.Summary()
        #pylint: disable=maybe-no-member
        summary.value.add(tag='time/selection', simple_value=duration)
        summary.value.add(tag='loss/triploss',simple_value=triplet_err)
        summary.value.add(tag='loss/total',simple_value=total_err)
        summary.value.add(tag='learning_rate/lr',simple_value=lr)
        summary_writer.add_summary(summary, step)
        
        batch_number += 1
        #with open('prefetch_cpu_var_2_{}.json'.format(batch_number),'w') as f:
        #    f.write(ctf)
    return step

def train_online(args, sess, epoch,
          learning_rate_placeholder, phase_train_placeholder, global_step, 
          loss, train_op, summary_op, summary_writer, learning_rate_schedule_file):
    batch_number = 0
    
    if args.learning_rate>0.0:
        lr = args.learning_rate
    else:
        lr = utils.get_learning_rate_from_file(learning_rate_schedule_file, epoch)
    while batch_number < args.epoch_size:
        # Sample people randomly from the dataset
        start_time = time.time()
        
        print('Running forward pass on sampled images: ', end='')
        feed_dict = {learning_rate_placeholder: lr, phase_train_placeholder: True}
        start_time = time.time()
        triplet_err,total_err, _, step = sess.run([loss['triplet_loss'],loss['total_loss'], train_op, global_step ], feed_dict=feed_dict)
        duration = time.time() - start_time
        print('Epoch: [%d][%d/%d]\tTime %.3f\tTriplet Loss %2.3f Total Loss %2.3f lr %2.5f' %
                  (epoch, batch_number+1, args.epoch_size, duration, triplet_err,total_err,lr))
        #ctf = tl.generate_chrome_trace_format()
        batch_number += 1
    return step
def select_triplets_by_distances(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    #pdb.set_trace()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []
    

    # here may be some bug, when applied to multi-gpu,the people_per_batch may less nrof_images_per_class, so this image overheading the people_per_batch will not consider.
    time_start = time.time()
    #for i in xrange(people_per_batch):
    for i in xrange(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in xrange(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            neg_dists_sqr = distances[a_idx,:]
            for pair in xrange(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx-p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    rnd_idx = np.random.randint(nrof_random_negs)
                    n_idx = all_neg[rnd_idx]
                    #n_idx = all_neg[sort_inds[0]]
                    #triplets.append((image_paths[a_idx], image_paths[p_idx], image_paths[n_idx]))
                    #triplets.extend([a_idx, p_idx, n_idx])
                    triplets.append([a_idx, p_idx, n_idx])
                    #print('Triplet %d: (%d, %d, %d), pos_dist=%2.6f, neg_dist=%2.6f (%d, %d, %d, %d, %d)' % 
                    #    (trip_idx, a_idx, p_idx, n_idx, pos_dist_sqr, neg_dists_sqr[n_idx], nrof_random_negs, rnd_idx, i, j, emb_start_idx))
                    trip_idx += 1

                num_trips += 1

        emb_start_idx += nrof_images

    #np.random.shuffle(triplets)
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {} nrof_choice_pairs {}'.format(num_trips,trip_idx))
    #return np.array(triplets,dtype=np.int64)
    triplet_inds = range(trip_idx)
    #pdb.set_trace()
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    #triplets = np.hstack(triplets[shuffle_inds].tolist()[0])
    triplets = np.hstack(triplets[triplet_inds])
    return triplets
def select_triplets_hardest(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    time_start = time.time()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []
    MAX=100000.


    for i in range(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in range(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            #pdb.set_trace()
            neg_dists_sqr = distances[a_idx,:].copy() # a bug occur if we don't use copy. because the code bellow will assign them to np.NaN 
            ''' 
            neg_dist_tmp = 100 # max_dist
            triplet_tmp = []
            for pair in range(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx, p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    n_idx = all_neg[sort_inds[0]]
                    if neg_dists_sqr[n_idx] < neg_dist_tmp:
                        neg_dist_tmp = neg_dists_sqr[n_idx]
                        triplet_tmp = [a_idx, p_idx, n_idx]
                    num_trips += 1
            if len(triplet_tmp) > 0:
                triplets.append(triplet_tmp)
                trip_idx += 1
            '''
            p_d = -1
            p_i = -1
            for pair in range(j, nrof_images):
                p_idx = emb_start_idx + pair
                pos_dist_sqr = distances[a_idx, p_idx]
                if pos_dist_sqr > p_d:
                    p_i = p_idx
                    p_d = pos_dist_sqr
            
            neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = MAX
            n_idx = neg_dists_sqr.argmin()
            triplets.append([a_idx,p_i,n_idx])

        emb_start_idx += nrof_images
    trip_idx = len(triplets)
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_choice_pairs {}'.format(trip_idx))
    triplet_inds = list(range(trip_idx))
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    triplets = np.hstack(triplets[triplet_inds])
    return triplets





def select_triplets_min_min(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    time_start = time.time()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []


    for i in range(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in range(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            #pdb.set_trace()
            neg_dists_sqr = distances[a_idx,:].copy() # a bug occur if we don't use copy. because the code bellow will assign them to np.NaN 
            neg_dist_tmp = 100 # max_dist
            triplet_tmp = []
            for pair in range(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx, p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    n_idx = all_neg[sort_inds[0]]
                    if neg_dists_sqr[n_idx] < neg_dist_tmp:
                        neg_dist_tmp = neg_dists_sqr[n_idx]
                        triplet_tmp = [a_idx, p_idx, n_idx]
                    num_trips += 1
            if len(triplet_tmp) > 0:
                triplets.append(triplet_tmp)
                trip_idx += 1

        emb_start_idx += nrof_images
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {} nrof_choice_pairs {}'.format(num_trips,trip_idx))
    triplet_inds = list(range(trip_idx))
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    triplets = np.hstack(triplets[triplet_inds])
    return triplets


def select_triplets_min_max(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    time_start = time.time()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []


    for i in range(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in range(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            #pdb.set_trace()
            neg_dists_sqr = distances[a_idx,:].copy() # a bug occur if we don't use copy. because the code bellow will assign them to np.NaN 
            neg_dist_tmp = -100 # max_dist
            triplet_tmp = []
            for pair in range(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx, p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    n_idx = all_neg[sort_inds[0]]
                    if neg_dists_sqr[n_idx] > neg_dist_tmp:
                        neg_dist_tmp = neg_dists_sqr[n_idx]
                        triplet_tmp = [a_idx, p_idx, n_idx]
                    num_trips += 1
            if len(triplet_tmp) > 0:
                triplets.append(triplet_tmp)
                trip_idx += 1

        emb_start_idx += nrof_images
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {} nrof_choice_pairs {}'.format(num_trips,trip_idx))
    triplet_inds = list(range(trip_idx))
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    triplets = np.hstack(triplets[triplet_inds])
    return triplets



def select_triplets_batch_random(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    time_start = time.time()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []


    for i in range(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in range(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            #pdb.set_trace()
            neg_dists_sqr = distances[a_idx,:].copy() # a bug occur if we don't use copy. because the code bellow will assign them to np.NaN 
            neg_dist_tmp = 100 # max_dist
            triplet_tmp = []
            for pair in range(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx, p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    rnd_idx = np.random.randint(nrof_random_negs)
                    n_idx = all_neg[rnd_idx]
                    #sort_inds = neg_dists_sqr[all_neg].argsort()
                    #n_idx = all_neg[sort_inds[0]]
                    triplet_tmp = [a_idx, p_idx, n_idx]
                    triplets.append(triplet_tmp)
                    num_trips += 1

        emb_start_idx += nrof_images
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {}'.format(num_trips))
    triplet_inds = list(range(len(triplets)))
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    triplets = np.hstack(triplets[triplet_inds])
    return triplets


def select_triplets_batch_all(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    time_start = time.time()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []


    for i in range(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in range(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            #pdb.set_trace()
            neg_dists_sqr = distances[a_idx,:].copy() # a bug occur if we don't use copy. because the code bellow will assign them to np.NaN 
            neg_dist_tmp = 100 # max_dist
            triplet_tmp = []
            for pair in range(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx, p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    #rnd_idx = np.random.randint(nrof_random_negs)
                    #n_idx = all_neg[rnd_idx]
                    #sort_inds = neg_dists_sqr[all_neg].argsort()
                    #n_idx = all_neg[sort_inds[0]]
                    #triplet_tmp = [a_idx, p_idx, n_idx]
                    triplet_tmp = [[a_idx, p_idx, n_idx] for n_idx in all_neg]
                    triplets.extend(triplet_tmp)
                    num_trips += len(triplet_tmp)

        emb_start_idx += nrof_images
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    total_triplets = len(triplets)
    clip_trips = min(trip_thresh,total_triplets)
    print('nrof_random_pairs {} and clip trips {}'.format(num_trips,clip_trips))
    triplet_inds = list(range(len(triplets)))
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    triplets = np.hstack(triplets[triplet_inds])
    triplets = triplets[:clip_trips]
    return triplets



 
def select_triplets_by_combine(distances, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    #pdb.set_trace()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    #embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []
    #0,1 for simi_hard,2 for hard,3 for hard_hard
    hard_hard_id = 7
    simi_hard_id = 6
    total_id = 8

    rand_id = np.random.randint(total_id)

    print('current selct strategy is {}'.format(rand_id))

    # here may be some bug, when applied to multi-gpu,the people_per_batch may less nrof_images_per_class, so this image overheading the people_per_batch will not consider.
    time_start = time.time()
    #for i in xrange(people_per_batch):
    if rand_id < hard_hard_id:
      for i in xrange(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in xrange(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            neg_dists_sqr = distances[a_idx,:]
            for pair in xrange(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx-p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    rnd_idx = np.random.randint(nrof_random_negs)
                    if rand_id == simi_hard_id:
                        n_idx = all_neg[sort_inds[0]]
                    else:
                        n_idx = all_neg[rnd_idx]
                    triplets.append([a_idx, p_idx, n_idx])
                    trip_idx += 1
                num_trips += 1
        emb_start_idx += nrof_images
    else:
      for i in xrange(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in xrange(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            #neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            neg_dists_sqr = distances[a_idx,:]
            neg_dist_tmp = 100 # max_dist
            triplet_tmp = []
            for pair in xrange(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                #pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                pos_dist_sqr = distances[a_idx-p_idx]
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    n_idx = all_neg[sort_inds[0]]
                    if neg_dists_sqr[n_idx] < neg_dist_tmp:
                        neg_dist_tmp = neg_dists_sqr[n_idx]
                        triplet_tmp = [a_idx, p_idx, n_idx]
                    num_trips += 1
            if len(triplet_tmp) > 0:
                triplets.append(triplet_tmp)
                trip_idx += 1

        emb_start_idx += nrof_images
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {} nrof_choice_pairs {}'.format(num_trips,trip_idx))
    triplet_inds = range(trip_idx)
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    triplets = np.hstack(triplets[triplet_inds])
    return triplets

 
def select_triplets(embeddings, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    #pdb.set_trace()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []
    
    # VGG Face: Choosing good triplets is crucial and should strike a balance between
    #  selecting informative (i.e. challenging) examples and swamping training with examples that
    #  are too hard. This is achieve by extending each pair (a, p) to a triplet (a, p, n) by sampling
    #  the image n at random, but only between the ones that violate the triplet loss margin. The
    #  latter is a form of hard-negative mining, but it is not as aggressive (and much cheaper) than
    #  choosing the maximally violating example, as often done in structured output learning.
    #pdb.set_trace()

    # here may be some bug, when applied to multi-gpu,the people_per_batch may less nrof_images_per_class, so this image overheading the people_per_batch will not consider.
    time_start = time.time()
    #for i in xrange(people_per_batch):
    for i in xrange(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in xrange(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            for pair in xrange(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                sort_inds = neg_dists_sqr[all_neg].argsort()
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    #rnd_idx = np.random.randint(nrof_random_negs)
                    #n_idx = all_neg[rnd_idx]
                    n_idx = all_neg[sort_inds[0]]
                    #triplets.append((image_paths[a_idx], image_paths[p_idx], image_paths[n_idx]))
                    #triplets.extend([a_idx, p_idx, n_idx])
                    triplets.append([a_idx, p_idx, n_idx])
                    #print('Triplet %d: (%d, %d, %d), pos_dist=%2.6f, neg_dist=%2.6f (%d, %d, %d, %d, %d)' % 
                    #    (trip_idx, a_idx, p_idx, n_idx, pos_dist_sqr, neg_dists_sqr[n_idx], nrof_random_negs, rnd_idx, i, j, emb_start_idx))
                    trip_idx += 1

                num_trips += 1

        emb_start_idx += nrof_images

    #np.random.shuffle(triplets)
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {} nrof_choice_pairs {}'.format(num_trips,trip_idx))
    #return np.array(triplets,dtype=np.int64)
    triplet_inds = range(trip_idx)
    #pdb.set_trace()
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    #triplets = np.hstack(triplets[shuffle_inds].tolist()[0])
    triplets = np.hstack(triplets[triplet_inds])
    return triplets

def select_triplets_hard(embeddings, labels, alpha):
    """ Select the triplets for training
    """
    #nrof_image_per_class = Counter(labels)
    #pdb.set_trace()
    label_counts = Counter(labels)
    nrof_images_per_class = [label_counts[l_ind] for l_ind in sorted(label_counts.keys())]
    embeddings = embeddings.squeeze()
    trip_idx = 0
    emb_start_idx = 0
    num_trips = 0
    triplets = []
    
    # VGG Face: Choosing good triplets is crucial and should strike a balance between
    #  selecting informative (i.e. challenging) examples and swamping training with examples that
    #  are too hard. This is achieve by extending each pair (a, p) to a triplet (a, p, n) by sampling
    #  the image n at random, but only between the ones that violate the triplet loss margin. The
    #  latter is a form of hard-negative mining, but it is not as aggressive (and much cheaper) than
    #  choosing the maximally violating example, as often done in structured output learning.
    #pdb.set_trace()

    # here may be some bug, when applied to multi-gpu,the people_per_batch may less nrof_images_per_class, so this image overheading the people_per_batch will not consider.
    time_start = time.time()
    #for i in xrange(people_per_batch):
    for i in xrange(len(nrof_images_per_class)):
        nrof_images = int(nrof_images_per_class[i])
        for j in xrange(1,nrof_images):
            a_idx = emb_start_idx + j - 1
            neg_dists_sqr = np.sum(np.square(embeddings[a_idx] - embeddings), 1)
            neg_dist_tmp = -1
            triplet_tmp = []
            for pair in xrange(j, nrof_images): # For every possible positive pair.
                p_idx = emb_start_idx + pair
                pos_dist_sqr = np.sum(np.square(embeddings[a_idx]-embeddings[p_idx]))
                neg_dists_sqr[emb_start_idx:emb_start_idx+nrof_images] = np.NaN
                #all_neg = np.where(np.logical_and(neg_dists_sqr-pos_dist_sqr<alpha, pos_dist_sqr<neg_dists_sqr))[0]  # FaceNet selection
                all_neg = np.where(neg_dists_sqr-pos_dist_sqr<alpha)[0] # VGG Face selecction
                nrof_random_negs = all_neg.shape[0]
                if nrof_random_negs>0:
                    sort_inds = neg_dists_sqr[all_neg].argsort()
                    #rnd_idx = np.random.randint(nrof_random_negs)
                    #n_idx = all_neg[rnd_idx]
                    n_idx = all_neg[sort_inds[0]]
                    if neg_dist_tmp < neg_dists_sqr[n_idx]:
                        #triplets.append((image_paths[a_idx], image_paths[p_idx], image_paths[n_idx]))
                        #triplets.extend([a_idx, p_idx, n_idx])
                        neg_dist_tmp = neg_dists_sqr[n_idx]
                        triplet_tmp = [a_idx, p_idx, n_idx]
                        #print('Triplet %d: (%d, %d, %d), pos_dist=%2.6f, neg_dist=%2.6f (%d, %d, %d, %d, %d)' % 
                        #    (trip_idx, a_idx, p_idx, n_idx, pos_dist_sqr, neg_dists_sqr[n_idx], nrof_random_negs, rnd_idx, i, j, emb_start_idx))

                    num_trips += 1
            if len(triplet_tmp) > 0:
                triplets.append(triplet_tmp)
                trip_idx += 1

        emb_start_idx += nrof_images

    #np.random.shuffle(triplets)
    time_select = time.time() - time_start
    print('time select triplet is {}'.format(time_select))
    print('nrof_random_pairs {} nrof_choice_pairs {}'.format(num_trips,trip_idx))
    #return np.array(triplets,dtype=np.int64)
    triplet_inds = range(len(triplets))
    #pdb.set_trace()
    np.random.shuffle(triplet_inds)
    triplets = np.array(triplets,dtype=np.int64)
    #triplets = np.hstack(triplets[shuffle_inds].tolist()[0])
    triplets = np.hstack(triplets[triplet_inds])
    return triplets


def argsort_label(label):
    '''
    get the true tensor from embedding
    
    '''
    arg_label = np.argsort(label)
    return arg_label

def sample_people(dataset, people_per_batch, images_per_person):
    nrof_images = people_per_batch * images_per_person
  
    # Sample classes from the dataset
    nrof_classes = len(dataset)
    class_indices = np.arange(nrof_classes)
    np.random.shuffle(class_indices)
    
    i = 0
    image_paths = []
    num_per_class = []
    sampled_class_indices = []
    #pdb.set_trace()
    # Sample images from these classes until we have enough
    while len(image_paths)<nrof_images:
        class_index = class_indices[i]
        nrof_images_in_class = len(dataset[class_index])
        image_indices = np.arange(nrof_images_in_class)
        np.random.shuffle(image_indices)
        nrof_images_from_class = min(nrof_images_in_class, images_per_person, nrof_images-len(image_paths))
        idx = image_indices[0:nrof_images_from_class]
        image_paths_for_class = [dataset[class_index].image_paths[j] for j in idx]
        sampled_class_indices += [class_index]*nrof_images_from_class
        image_paths += image_paths_for_class
        num_per_class.append(nrof_images_from_class)
        i+=1
  
    return image_paths, num_per_class

def sample_people_multi(dataset, people_per_batch, images_per_person,num_gpus):
    nrof_images = people_per_batch * images_per_person
  
    # Sample classes from the dataset
    nrof_classes = len(dataset)
    class_indices = np.arange(nrof_classes)
    np.random.shuffle(class_indices)
   
    gpu_ind = 0
    multi_paths = []
    multi_num_per_class = []
    paths_split = []
    num_per_class_split = []
    i = 0
    for _ in range(num_gpus): 
        image_paths = []
        num_per_class = []
        sampled_class_indices = []
        #paths_count = 0
        num_per_class_count = 0
        # Sample images from these classes until we have enough
        while len(image_paths)<nrof_images:
            class_index = class_indices[i]
            nrof_images_in_class = len(dataset[class_index])
            image_indices = np.arange(nrof_images_in_class)
            np.random.shuffle(image_indices)
            nrof_images_from_class = min(nrof_images_in_class, images_per_person, nrof_images-len(image_paths))
            idx = image_indices[0:nrof_images_from_class]
            image_paths_for_class = [dataset[class_index].image_paths[j] for j in idx]
            sampled_class_indices += [class_index]*nrof_images_from_class
            image_paths += image_paths_for_class
            num_per_class.append(nrof_images_from_class)
            i+=1
            num_per_class_count += 1
        paths_split.append(len(image_paths))
        num_per_class_split.append(num_per_class_count)
        multi_paths.extend(image_paths)
        multi_num_per_class.extend(num_per_class)
  
    return multi_paths, multi_num_per_class,paths_split,num_per_class_split


def evaluate(sess, image_paths, embeddings, labels_batch, image_paths_placeholder, labels_placeholder, 
        batch_size_placeholder, learning_rate_placeholder, phase_train_placeholder, enqueue_op, actual_issame, batch_size, 
        nrof_folds, log_dir, step, summary_writer, embedding_size):
    start_time = time.time()
    # Run forward pass to calculate embeddings
    print('Running forward pass on LFW images: ', end='')
    
    nrof_images = len(actual_issame)*2
    assert(len(image_paths)==nrof_images)
    labels_array = np.reshape(np.arange(nrof_images),(-1,3))
    image_paths_array = np.reshape(np.expand_dims(np.array(image_paths),1), (-1,3))
    sess.run(enqueue_op, {image_paths_placeholder: image_paths_array, labels_placeholder: labels_array})
    emb_array = np.zeros((nrof_images, embedding_size))
    nrof_batches = int(np.ceil(nrof_images / batch_size))
    label_check_array = np.zeros((nrof_images,))
    for i in xrange(nrof_batches):
        batch_size = min(nrof_images-i*batch_size, batch_size)
        emb, lab = sess.run([embeddings, labels_batch], feed_dict={batch_size_placeholder: batch_size,
            learning_rate_placeholder: 0.0, phase_train_placeholder: False})
        emb_array[lab,:] = emb
        label_check_array[lab] = 1
    print('%.3f' % (time.time()-start_time))
    
    assert(np.all(label_check_array==1))
    
    _, _, accuracy, val, val_std, far = lfw.evaluate(emb_array, actual_issame, nrof_folds=nrof_folds)
    
    print('Accuracy: %1.3f+-%1.3f' % (np.mean(accuracy), np.std(accuracy)))
    print('Validation rate: %2.5f+-%2.5f @ FAR=%2.5f' % (val, val_std, far))
    lfw_time = time.time() - start_time
    # Add validation loss and accuracy to summary
    summary = tf.Summary()
    #pylint: disable=maybe-no-member
    summary.value.add(tag='lfw/accuracy', simple_value=np.mean(accuracy))
    summary.value.add(tag='lfw/val_rate', simple_value=val)
    summary.value.add(tag='time/lfw', simple_value=lfw_time)
    summary_writer.add_summary(summary, step)
    with open(os.path.join(log_dir,'lfw_result.txt'),'at') as f:
        f.write('%d\t%.5f\t%.5f\n' % (step, np.mean(accuracy), val))

def save_variables_and_metagraph(sess, saver, summary_writer, model_dir, model_name, step):
    # Save the model checkpoint
    print('Saving variables')
    start_time = time.time()
    checkpoint_path = os.path.join(model_dir, 'model-%s.ckpt' % model_name)
    saver.save(sess, checkpoint_path, global_step=step, write_meta_graph=False)
    save_time_variables = time.time() - start_time
    print('Variables saved in %.2f seconds' % save_time_variables)
    metagraph_filename = os.path.join(model_dir, 'model-%s.meta' % model_name)
    save_time_metagraph = 0  
    if not os.path.exists(metagraph_filename):
        print('Saving metagraph')
        start_time = time.time()
        saver.export_meta_graph(metagraph_filename)
        save_time_metagraph = time.time() - start_time
        print('Metagraph saved in %.2f seconds' % save_time_metagraph)
    summary = tf.Summary()
    #pylint: disable=maybe-no-member
    summary.value.add(tag='time/save_variables', simple_value=save_time_variables)
    summary.value.add(tag='time/save_metagraph', simple_value=save_time_metagraph)
    summary_writer.add_summary(summary, step)
  
  
def get_learning_rate_from_file(filename, epoch):
    with open(filename, 'r') as f:
        for line in f.readlines():
            line = line.split('#', 1)[0]
            if line:
                par = line.strip().split(':')
                e = int(par[0])
                lr = float(par[1])
                if e <= epoch:
                    learning_rate = lr
                else:
                    return learning_rate
    

def parse_arguments(argv):
    parser = argparse.ArgumentParser()
    
    parser.add_argument('--logs_base_dir', type=str, 
        help='Directory where to write event logs.', default='logs/facenet_ms_mp')
    parser.add_argument('--models_base_dir', type=str,
        help='Directory where to write trained models and checkpoints.', default='models/facenet_ms_mp')
    parser.add_argument('--gpu_memory_fraction', type=float,
        help='Upper bound on the amount of GPU memory that will be used by the process.', default=.9)
    parser.add_argument('--pretrained_model', type=str,
        help='Load a pretrained model before training starts.')
    parser.add_argument('--data_dir', type=str,
        help='Path to the data directory containing aligned face patches. Multiple directories are separated with colon.',
        default='~/datasets/casia/casia_maxpy_mtcnnalign_182_160')
    parser.add_argument('--model_def', type=str,
        help='Model definition. Points to a module containing the definition of the inference graph.', default='models.inception_resnet_v1')
    parser.add_argument('--max_nrof_epochs', type=int,
        help='Number of epochs to run.', default=80)
    parser.add_argument('--batch_size', type=int,
        help='Number of images to process in a batch.', default=90)
    parser.add_argument('--image_size', type=int,
        help='Image size (height, width) in pixels.', default=224)
    parser.add_argument('--image_src_size', type=int,
        help='Src Image size (height, width) in pixels.', default=256)
    parser.add_argument('--people_per_batch', type=int,
        help='Number of people per batch.', default=30)
    parser.add_argument('--num_gpus', type=int,
        help='Number of gpus.', default=4)
    parser.add_argument('--scale', type=int,
        help='scale batch of forward .', default=10)
    parser.add_argument('--images_per_person', type=int,
        help='Number of images per person.', default=7)
    parser.add_argument('--epoch_size', type=int,
        help='Number of batches per epoch.', default=60)
    parser.add_argument('--alpha', type=float,
        help='Positive to negative triplet distance margin.', default=0.2)
    parser.add_argument('--embedding_size', type=int,
        help='Dimensionality of the embedding.', default=512)
    parser.add_argument('--random_crop', 
        help='Performs random cropping of training images. If false, the center image_size pixels from the training images are used. ' +
         'If the size of the images in the data directory is equal to image_size no cropping is performed', action='store_true')
    parser.add_argument('--random_flip', 
        help='Performs random horizontal flipping of training images.', action='store_true')
    parser.add_argument('--show_triplet', 
        help='show the select triplet pair',action='store_true')
    parser.add_argument('--keep_probability', type=float,
        help='Keep probability of dropout for the fully connected layer(s).', default=1.0)
    parser.add_argument('--weight_decay', type=float,
        help='L2 weight regularization.', default=0.0)
    parser.add_argument('--optimizer', type=str, choices=['ADAGRAD', 'ADADELTA', 'ADAM', 'RMSPROP', 'MOM','SGD'],
        help='The optimization algorithm to use', default='ADAGRAD')
    parser.add_argument('--learning_rate', type=float,
        help='Initial learning rate. If set to a negative value a learning rate ' +
        'schedule can be specified in the file "learning_rate_schedule.txt"', default=0.1)
    parser.add_argument('--learning_rate_decay_epochs', type=int,
        help='Number of epochs between learning rate decay.', default=100)
    parser.add_argument('--learning_rate_decay_factor', type=float,
        help='Learning rate decay factor.', default=1.0)
    parser.add_argument('--moving_average_decay', type=float,
        help='Exponential decay for tracking of training parameters.', default=0.9999)
    parser.add_argument('--seed', type=int,
        help='Random seed.', default=6686)
        #help='Random seed.', default=666)
    parser.add_argument('--learning_rate_schedule_file', type=str,
        help='File containing the learning rate schedule that is used when learning_rate is set to to -1.', default='data/learning_rate_schedule.txt')

   
    parser.add_argument('--network', type=str,
        help='Which network to use.', default='resnet_v1')
    parser.add_argument('--strategy', type=str,
        help='triplet strategy to use.', default='min_and_max')
    parser.add_argument('--mine_method', type=str,
        help='hard example mine method to use.', default='simi_online')
    parser.add_argument('--dataset', type=str,
        help='Which dataset used to train model',default='mega')
    
    return parser.parse_args(argv)
  

if __name__ == '__main__':
    main(parse_arguments(sys.argv[1:]))
