import itertools
import os
import pathlib
import matplotlib.pylab as plt
import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
import pandas as pd
from math import ceil, floor
from timeit import default_timer as timer

np.random.seed(400)
shuffle = True
AUTOTUNE = tf.data.experimental.AUTOTUNE
print("TF version:", tf.__version__)
print("Hub version:", hub.__version__)
print("Availables GPU:")
print(tf.config.list_physical_devices('GPU') if tf.config.list_physical_devices('GPU') != [] else 'No GPU available')
os.environ["TFHUB_CACHE_DIR"] = "C:/Users/Ennio/AppData/Local/Temp/model"

# read triplets
train_triplets_df = pd.read_csv('../data/train_triplets.txt', delimiter=' ', header=None)
test_triplets_df = pd.read_csv('../data/test_triplets.txt', delimiter=' ', header=None)
train_triplets_df.columns = ['A', 'B', 'C']
test_triplets_df.columns = ['A', 'B', 'C']

# swap half
N_train = len(train_triplets_df.index)
N_test = len(test_triplets_df.index)
swapped_train_triplets_df = train_triplets_df.iloc[:int(N_train / 2), :]
swapped_train_triplets_df.columns = ['A', 'C', 'B']
train_triplets_df = pd.concat((swapped_train_triplets_df, train_triplets_df.iloc[int(N_train / 2):, :]), sort=True)
# train_triplets_dict = {index: list(row) for index, row in train_triplets_df.iterrows()}

# create Y
Y_train_np = (np.arange(N_train) >= int(N_train / 2)) * 1

if shuffle:
    rd_permutation = np.random.permutation(train_triplets_df.index)
    train_triplets_df = train_triplets_df.reindex(rd_permutation).set_index(np.arange(0, train_triplets_df.shape[0], 1))
    Y_train_np = Y_train_np[rd_permutation]

# tensor for Y_train
Y_train_ts = tf.constant(Y_train_np)

pixels = 299
IMAGE_SIZE = (pixels, pixels)

BATCH_SIZE = 64
data_dir = '../data/food/'
data_dir = pathlib.Path(data_dir)


def label2path(label):
    return '../data/food/' + str(label).zfill(5) + '.jpg'


def get_img(file_path):
    img = tf.io.read_file(file_path)
    # convert the compressed string to a 3D uint8 tensor
    img = tf.image.decode_jpeg(img, channels=3)

    # resize the image to the desired size.
    img = tf.image.resize(img, IMAGE_SIZE)

    # # Use `convert_image_dtype` to convert to floats in the [0,1] range.
    # img = tf.image.convert_image_dtype(img, tf.float32)
    return img / 255


def build_image_triplet(label_triple):
    return (get_img(label2path(label_triple[0])), get_img(label2path(label_triple[1])),
            get_img(label2path(label_triple[2])))


def X_train_generator():
    for index, row in train_triplets_df.iterrows():
        yield build_image_triplet(list(row))


def X_test_generator():
    for _, row in test_triplets_df.iterrows():
        yield build_image_triplet(list(row))


X_train = tf.data.Dataset.from_generator(X_train_generator,
                                         (tf.float32, tf.float32, tf.float32),
                                         output_shapes=(tf.TensorShape([pixels, pixels, 3]),) * 3
                                         )

X_test = tf.data.Dataset.from_generator(X_test_generator,
                                        (tf.float32, tf.float32, tf.float32),
                                        output_shapes=(tf.TensorShape([pixels, pixels, 3]),) * 3,
                                        ).batch(BATCH_SIZE)

Y_train = tf.data.Dataset.from_tensor_slices(Y_train_ts)
zipped_train = tf.data.Dataset.zip((X_train, Y_train)).batch(BATCH_SIZE)
print()
# # debug only
# X_train_it = X_train.as_numpy_iterator()
# Y_train_it = Y_train.as_numpy_iterator()
# zipped_train_it = zipped_train.as_numpy_iterator()
# next(X_train_it)
# next(Y_train_it)
# next(zipped_train_it)
#
# # verify X_test is not shuffled
# first_in_df = build_image_triplet(list(test_triplets_df.iloc[0,:]))[0].numpy()
# first_in_X_test = next(X_test.as_numpy_iterator())[0]


# build the model
input_shape = (299, 299, 3)
# input_A = tf.keras.layers.Input(shape=input_shape, name='input_A'),
# input_B = tf.keras.layers.Input(shape=input_shape, name='input_B'),
# input_C = tf.keras.layers.Input(shape=input_shape, name='input_C'),


def input_block(name, kernel_size, filters, input_shape):
    return tf.keras.Sequential([
        tf.keras.layers.Conv2D(kernel_size=(kernel_size, kernel_size), filters=filters, name='input_' + name, input_shape=input_shape),
        tf.keras.layers.Activation('relu'),
        tf.keras.layers.MaxPooling2D(pool_size=(2, 2))
    ])

model_A = input_block(name='A1', kernel_size=5, filters=16, input_shape=input_shape)
model_B = input_block(name='B1', kernel_size=5, filters=16, input_shape=input_shape)
model_C = input_block(name='C1', kernel_size=5, filters=16, input_shape=input_shape)

model_A.build((None,)+input_shape)
model_B.build((None,)+input_shape)
model_C.build((None,)+input_shape)


def conv_block(x, name, kernel_size, filters, input_shape=None):
    x = tf.keras.layers.Conv2D(kernel_size=(kernel_size, kernel_size), filters=filters, name='conv' + name)(x)
    x = tf.keras.layers.Activation('relu')(x)
    x = tf.keras.layers.MaxPooling2D(pool_size=(2, 2))(x)
    return x

x_A = conv_block(model_A.output, 'A2', kernel_size=5, filters=32)
x_B = conv_block(model_B.output, 'B2', kernel_size=5, filters=32)
x_C = conv_block(model_C.output, 'C2', kernel_size=5, filters=32)


x = tf.keras.layers.Concatenate(axis=1)([x_A, x_B, x_C])
x = tf.keras.layers.Flatten()(x)
x = tf.keras.layers.Dense(64)(x)
x = tf.keras.layers.Activation('relu')(x)
x = tf.keras.layers.Dropout(0.5)(x)
x = tf.keras.layers.Dense(1)(x)
output = tf.keras.layers.Activation('sigmoid')(x)

model = tf.keras.Model(inputs=[model_A.input, model_B.input, model_C.input], outputs=output, name='task4_CNN')

model.summary()

tf.keras.utils.plot_model(
   model, to_file='model.png', show_shapes=True, show_layer_names=True)

model.compile(optimizer=tf.keras.optimizers.Adam(),
              loss=tf.keras.losses.mean_squared_error,
              metrics=[tf.keras.metrics.categorical_accuracy]
              )

print('Training started')
model.fit(zipped_train, steps_per_epoch=2, epochs=1, verbose=1, use_multiprocessing=True)

start = timer()
model.predict([np.ones([BATCH_SIZE, 299, 299, 3]), ] * 3)
end = timer()
elapsed = end - start
print(str(round(elapsed, 2)) + " sec to predict a batch of " + str(BATCH_SIZE)
      + ", 59516 samples will be evaluated in " + str(round(59516 / BATCH_SIZE * elapsed, 2)) + "sec")


def batch_predict(X, N):
    X_it = X.as_numpy_iterator()
    Y_batch = np.zeros([0, 2])
    for n in range(0, N, BATCH_SIZE):  # N = 59516 ==>
        start = timer()
        Y_batch = np.row_stack([Y_batch, model.predict(next(X_it))])
        end = timer()
        print('Predicted until ' + str(n) + ', ' + str(round(end - start, 2)) + 's')
    print('Predicted')
    return Y_batch


Y_test = batch_predict(X_test, N_test)
pd.DataFrame(data=Y_test[:, 0], columns=None, index=None).to_csv("sumbission.csv", index=None, header=None)
print('Done')