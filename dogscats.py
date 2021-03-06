'''
Acknowledging Kaggle contributor Uysim (http://wwww.kaggle.com/uysimty)
Uysim's Kaggle kernel was utilized as reference for handling
the dogs vs cats dataset and cleaning steps. Thanks Uysim.
'''

import os
import datetime as dt
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from sklearn.model_selection import train_test_split
from tensorflow.compat.v1 import ConfigProto, Session, RunOptions
from tensorflow.compat.v1.keras.backend import set_session
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

from ensemblenet import StackingModel

# Run Options
np.random.seed(0)  # Seed for reproducing
tf.keras.fit_verbose = 2  # Print status after every epoch
RunOptions.report_tensor_allocations_upon_oom = True  # Out-of-memory display
config = ConfigProto()
config.gpu_options.allow_growth = True  # dynamically grow GPU memory
config.log_device_placement = True
sess = Session(config=config)
set_session(sess)

# Image settings
IMAGE_WIDTH = 128
IMAGE_HEIGHT = 128
IMAGE_SIZE = (IMAGE_WIDTH, IMAGE_HEIGHT)
IMAGE_CHANNELS = 3  # RGB
train_path = 'c:/users/matthew/projects/data/dogs-vs-cats/train/train/'
test_path = 'c:/users/matthew/projects/data/dogs-vs-cats/test1/test1/'
file_frac = 1
batch_size = 16

# Model Hyperparameters
main_epochs = 50  # Epochs for meta learner
sub_epochs = 50  # Epochs for base models
num_classes = 2  # Number of classes to predict
num_sub_models = 5  # Number of base models
num_dense_layers = 2  # Number of dense layers in each base model
num_conv_layers = 3
# Neurons in dense layers above
dense_shapes = list(map(
    lambda x: sorted(tuple(x), reverse=True),
    np.random.randint(200, 2000, (num_sub_models, num_dense_layers))
))
# Out-channels in convolutional layers of base models
conv_shapes = list(map(
    lambda x: sorted(tuple(2 ** x)),
    np.random.randint(3, 8, (num_sub_models, num_conv_layers))
))

conv_shapes = ((32, 64, 128), (16, 32, 64), (8, 16, 32), (32, 64, 128), (16,
                                                                         64,
                                                                         128))

# Callbacks for modifying learning as we train
early_stop_sub = EarlyStopping(patience=12)
learning_rate_sub = ReduceLROnPlateau(monitor='val_loss', patience=6,
                                     factor=0.1)
early_stop_main = EarlyStopping(patience=10)
learning_rate_main = ReduceLROnPlateau(monitor='val_loss', patience=4,
                                       factor=0.5)
# Logging for Tensorboard
log_dir_sub = "./logs/fit/submodels/" + dt.datetime.now().strftime(
    "%Y%m%d-%H%M%S")
log_dir_main = "./logs/fit/main/" + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
tensorboard_callback_main = tf.keras.callbacks.TensorBoard(
    log_dir=log_dir_main, histogram_freq=1
)

# Main script, data collection and training
def main():
    filenames = os.listdir(train_path)
    categories = []
    for filename in filenames:
        category = filename.split('.')[0]
        if category == 'dog':
            categories.append(1)
        else:
            categories.append(0)

    file_df = pd.DataFrame({'filename': filenames, 'category': categories})
    # Filter down samples to allow for dev
    file_df = file_df.sample(frac=file_frac)
    file_df['category'].replace({0: 'cat', 1: 'dog'}, inplace=True)

    # Create training, validation, test dfs
    train_val_df, test_df = train_test_split(file_df, test_size=0.1,
                                             random_state=0)
    train_df, val_df = train_test_split(train_val_df, test_size=0.2,
                                        random_state=0)
    train_df.reset_index(drop=True, inplace=True)
    val_df.reset_index(drop=True, inplace=True)

    total_train = train_df.shape[0]
    total_validate = val_df.shape[0]

    train_datagen = ImageDataGenerator(
        rotation_range=15,
        rescale=1. / 255,
        shear_range=0.1,
        zoom_range=0.2,
        horizontal_flip=True,
        width_shift_range=0.1,  # 0.1
        height_shift_range=0.1  # 0.1
    )
    train_generator = train_datagen.flow_from_dataframe(
        train_df,
        train_path,
        x_col='filename',
        y_col='category',
        target_size=IMAGE_SIZE,
        class_mode='categorical',
        batch_size=batch_size
    )
    val_datagen = ImageDataGenerator(rescale=1. / 255)
    val_generator = val_datagen.flow_from_dataframe(
        val_df,
        train_path,
        x_col='filename',
        y_col='category',
        target_size=IMAGE_SIZE,
        class_mode='categorical',
        batch_size=batch_size
    )

    compile_params = {
        'loss': "categorical_crossentropy",
        'optimizer': 'RMSprop',
        'metrics': ['accuracy']
    }
    fit_params = (
        [train_generator],
        {'epochs': sub_epochs,
         'validation_data': val_generator,
         'validation_steps': total_validate // batch_size,
         'steps_per_epoch': total_train // batch_size,
         'verbose': 2,
         'callbacks': [early_stop_sub, learning_rate_sub],
         }
    )
    fit_params2 = (
        [train_generator],
        {'epochs': main_epochs,
         'validation_data': val_generator,
         'validation_steps': total_validate // batch_size,
         'steps_per_epoch': total_train // batch_size,
         'verbose': 2,
         'callbacks': [early_stop_main, learning_rate_main,
                       tensorboard_callback_main],
         }
    )

    model = StackingModel(
        num_classes, compile_params, fit_params,
        dense_shapes, conv_shapes, trainable=False,
        logging=log_dir_sub
    )
    model.compile(**compile_params)
    model.fit(*fit_params2[0], **fit_params2[1])

    test_datagen = ImageDataGenerator(rescale=1. / 255)
    test_generator = test_datagen.flow_from_dataframe(
        test_df,
        train_path,  # A little bit unorthodox, but we only have labeled train
        # images
        x_col='filename',
        y_col=None,
        class_mode=None,
        target_size=IMAGE_SIZE,
        batch_size=batch_size,
        shuffle=False
    )


    # Model Assessment
    def model_accuracy(test_generator) -> float:
        pred_class = model.predict(test_generator)
        pred = np.round(pred_class[:, 1])
        test_df['category'].replace(['cat', 'dog'], [0, 1], inplace=True)
        truth = test_df['category']
        accuracy = np.mean(pred == truth)
        return accuracy

    accuracy = model_accuracy(test_generator)
    print("Model Accuracy: ", accuracy)
    return model

if __name__ == '__main__':
    model = main()
