import matplotlib.pyplot as plt
import sys, os.path
from time import sleep

from utils import get_random_batch, unit_circle_to_scale, scale_to_unit_circle
from keras.models import Graph
from keras.layers.core import Dense, Activation, Dropout, TimeDistributedDense
from keras.layers.recurrent import LSTM, GRU
from keras.callbacks import ModelCheckpoint, EarlyStopping

import numpy as np

save_model_path = "./pretrained_models/" + sys.argv[0] + ".h5"

len_circ_repr = 4
def time_representation(dti):
    repres=[]
    secs = (dti.minute%2)*60 + dti.second
    repres += scale_to_unit_circle(secs, 120)
    mins = (dti.hour%2)*60 + dti.minute
    repres += scale_to_unit_circle(mins, 120)

    return repres

def label_representation(y, i, dti):
    y[i, (dti.minute%2)*60 + dti.second] = 1
    y[i, (dti.hour%2)*60 + dti.minute]
    
def load_model(graph):
    if os.path.isfile(save_model_path):
        print("Loading best model so far...")
        graph.load_weights(save_model_path)
    
def build_model():
    print('Build model...')
    graph = Graph()
    graph.add_input(name='input', ndim=3)
    graph.add_node(GRU(len_circ_repr, 128, return_sequences=True), name='gru1', input='input')
    graph.add_node(TimeDistributedDense(128, 128), name='tdd', input='gru1')
    graph.add_node(GRU(128, 128, return_sequences=False), name='gru2', input='tdd')
    graph.add_node(Dense(128, 120, activation='softmax'), name='seconds', input='gru2')
    graph.add_node(Dense(128, 120, activation='softmax'), name='minutes', input='gru2')
    graph.add_output(name='out1', input='seconds')
    graph.add_output(name='out2', input='minutes')
    
    print('Compile model...')
    graph.compile('rmsprop', {'out1':'categorical_crossentropy', 'out2':'categorical_crossentropy'})
    return graph


def train_model(graph):
    nb_iter = 1
    nb_epochs = 10000
    len_seq=20
    num_seqs=100000

    seq_params = {
        "freqs":{'S':1},
        "add_noise": False,
        "mult": 60,
        "time_repr":time_representation,
        "label_repr":label_representation
    }
    X_train = np.zeros((num_seqs, len_seq, len_circ_repr), dtype=np.float)
    y_train = np.zeros((num_seqs, 240), dtype=np.bool)

    from monitoring import LossHistory
    history = LossHistory()
    checkpointer = ModelCheckpoint(filepath=save_model_path, verbose=1, save_best_only=True)

    for e in range(nb_iter):
        print('-'*40)
        print('Iteration', e)
        print('-'*40)

        print("Generating training data...")
        get_random_batch(X_train, y_train, seq_params)
        print("Fitting data...")
        earlystopper = EarlyStopping(monitor='val_loss', patience=25, verbose=2)
        graph.fit({'input':X_train, 'out1':y_train[:,:120], 'out2':y_train[:,120:]}, validation_split = 0.3, batch_size=128, nb_epoch=nb_epochs, callbacks=[checkpointer, earlystopper, history]) 


def next_prediction(graph, seq):
    y_pred = graph.predict({'input':seq}, verbose=0)
    return y_pred['out1'][0,:], y_pred['out2'][0,:]


def demo(graph):
    plt.ion()
    fig_size = plt.rcParams["figure.figsize"]
    fig_size[0] = 16
    fig_size[1] = 12
    plt.rcParams["figure.figsize"] = fig_size
    f, (ax3) = plt.subplots(1, 2, sharey=True)
    ax2.set_title('M')
    ax2.set_ylim(ymax = 1, ymin = 0)
    ax2.set_xlim(xmax = 59, xmin = 0)

    ax3.set_title('S')
    ax3.set_ylim(ymax = 1, ymin = 0)
    ax3.set_xlim(xmax = 59, xmin = 0)
    plt.xticks(np.arange(0, 60, 1.0))

    prob_seconds, = ax3.plot([], [], linewidth=2.0)
    true_seconds = ax3.bar(range(60), np.zeros(60), width=0.5, color='lightpink', align='center')

    prob_minutes, = ax3.plot([], [], linewidth=2.0)
    true_minutes = ax3.bar(range(60), np.zeros(60), width=0.5, color='lightpink', align='center')

    num_seqs = 100
    len_seq = 10
    X = np.zeros((num_seqs, len_seq, len_circ_repr), dtype=np.float)
    y = np.zeros((num_seqs, 240), dtype=np.bool)

    seq_params = {
        #"freqs":{'D':86400,'H':3600,'T':60,'S':1, 'B':86400, 'W-SUN':86400*7 },
        "freqs":{'S':1},
        "add_noise": False,
        "mult": 60,
        "time_repr":time_representation,
        "label_repr": label_representation,
    }

    freqs, data = get_random_batch(X, y, seq_params)

    for s in range(num_seqs):
        f.suptitle("freqency: " + str(freqs[s+len_seq]), fontsize=20)

        secs_preds, mins_preds = next_prediction(graph, X[s:s+1, :, :])
        secs_pred_probs = np.maximum(secs_preds[:60], secs_preds[60:])
        mins_pred_probs = np.maximum(mins_preds[:60], mins_preds[60:])

        prob_seconds.set_ydata(pred_probs)
        prob_seconds.set_xdata(range(60))

        prob_minutes.set_ydata(pred_probs)
        prob_minutes.set_xdata(range(60))

        secs = np.argmax(y[s][:120])%60
        for i,b in enumerate(true_seconds):
            if i == secs:
                b.set_height(1)
            else:
                b.set_height(0)

        mins = np.argmax(y[s][120:])%60
        for i,b in enumerate(true_minutes):
            if i == mins:
                b.set_height(1)
            else:
                b.set_height(0)

        f.canvas.draw()
        sleep(2)



if __name__ == '__main__':
    graph = build_model()
    #train_model(graph)
    load_model(graph)
    demo(graph)

