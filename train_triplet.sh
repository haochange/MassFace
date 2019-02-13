#NETWORK="resnet_v2"
NETWORK='mobilenet'
DATASET='webface'
#STRATEGY='min_and_min'
STRATEGY='min_and_max'
#STRATEGY='hardest'
#STRATEGY='batch_random'
#STRATEGY='batch_all'
#MINE_METHOD='simi_online'
MINE_METHOD='online'
#DATA_DIR='dataset/casia-112x112'
#DATA_DIR='local_dataset/webface_112x112'
DATA_DIR='/workspace/data/face/webface_112x112' # data located in hard disk
#DATA_DIR='dataset/debug'
#PRETRAINED_MODEL="pretrained_model/model-20181222-102734.ckpt-60000"
#PRETRAINED_MODEL='mobilenet_model/model-20181226-131708.ckpt-43200'
#PRETRAINED_MODEL='/workspace/project/CosFace/models/mobilenet_softmax_112_2_64._2._0.35_ADAM_--fc_bn_112_1024/20181226-131708/model-20181226-131708.ckpt-43200' # for mobilenet
PRETRAINED_MODEL=/workspace/saved/softmax/models/mobilenet_cosface_112_2_64._2._0.25_ADAM_--fc_bn_112_1024/20190201-081843/model-20190201-081843.ckpt-60000
#PRETRAINED_MODEL='models/mobilenet_webface_batch_random_online_more/20190105-223010/model-20190105-223010.ckpt-230700'
#PRETRAINED_MODEL='models/mobilenet_webface_min_and_min_online_more/20190101-100706/model-20190101-100706.ckpt-60000'
#PRETRAINED_MODEL='models/mobilenet_webface_min_and_min_online_more/20190101-210616/model-20190101-210616.ckpt-413220'
#PRETRAINED_MODEL='models/mobilenet_webface_min_and_min_online_op/20181228-131906/model-20181228-131906.ckpt-24780'
#P=21
#K=10
P=41
K=5
#P=14
#K=15
#P=10
#K=21
#P=30
#K=7
NAME=${NETWORK}_${DATASET}_${STRATEGY}_${MINE_METHOD}__${P}_${K}_more
SAVE_DIR=/workspace/saved/triplet
#CMD="\" bash -c 'CUDA_VISIBLE_DEVICES=0 python /workspace/project/TripletFace/train.py --logs_base_dir ${SAVE_DIR}logs/${NAME}/ --models_base_dir ${SAVE_DIR}/models/${NAME}/  --image_size 224  --optimizer ADAGRAD --learning_rate 0.001 --weight_decay 1e-4 --max_nrof_epochs 10000  --network ${NETWORK} --dataset ${DATASET} --data_dir ${DATA_DIR} --pretrained_model ${PRETRAINED_MODEL} --random_crop --random_flip --image_size 112 --strategy ${STRATEGY} --mine_method ${MINE_METHOD} --num_gpus 1 --embedding_size 1024 --scale 10 --people_per_batch ${P} --images_per_person ${K}'\""
CMD="\" bash -c 'python /workspace/project/MassFace/train/train_triplet.py --logs_base_dir ${SAVE_DIR}logs/${NAME}/ --models_base_dir ${SAVE_DIR}/models/${NAME}/  --image_size 224  --optimizer ADAGRAD --learning_rate 0.001 --weight_decay 1e-4 --max_nrof_epochs 10000  --network ${NETWORK} --dataset ${DATASET} --data_dir ${DATA_DIR} --pretrained_model ${PRETRAINED_MODEL} --random_crop --random_flip --image_size 112 --strategy ${STRATEGY} --mine_method ${MINE_METHOD} --num_gpus 1 --embedding_size 1024 --scale 10 --people_per_batch ${P} --images_per_person ${K}'\""
LOCAL_CMD="python /workspace/project/MassFace/train/train_triplet.py --logs_base_dir ${SAVE_DIR}logs/${NAME}/ --models_base_dir ${SAVE_DIR}/models/${NAME}/  --image_size 224  --optimizer ADAGRAD --learning_rate 0.001 --weight_decay 1e-4 --max_nrof_epochs 10000  --network ${NETWORK} --dataset ${DATASET} --data_dir ${DATA_DIR} --pretrained_model ${PRETRAINED_MODEL} --random_crop --random_flip --image_size 112 --strategy ${STRATEGY} --mine_method ${MINE_METHOD} --num_gpus 1 --embedding_size 1024 --scale 10 --people_per_batch ${P} --images_per_person ${K}"
echo ${LOCAL_CMD} && eval ${LOCAL_CMD}
cmd="axer create --name='test_lip_cos' --cmd=${CMD} --gpu_count='1' --image='CV-Caffe_TF1.8-Py3' --prior_gpu_kind='V100' --project_id 332"
#echo ${cmd}  && eval ${cmd}
