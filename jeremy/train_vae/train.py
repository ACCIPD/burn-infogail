import os, sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import cPickle
from dataloader import DataLoader
import h5py
import numpy as np
import os
import tensorflow as tf
import time
from utils import latent_viz_pure, save_h5, latent_viz_mixed, load_h5
import matplotlib.pyplot as plt
import vae

DOMAINS = [0, 1, 2, 3]

from rllab.config import EXPERT_PATH

def main():
    parser = argparse.ArgumentParser()
    #parser.add_argument('--save_dir',           type=str,   default='./models', help='directory to store checkpointed models')
    parser.add_argument('--ckpt_name',          type= str,  default='',         help='name of checkpoint file to load (blank means none)')

    parser.add_argument('--batch_size',         type=int,   default=  60,        help='minibatch size')
    parser.add_argument('--state_dim',          type=int,   default=  51,       help='number of state variables')
    parser.add_argument('--action_dim',         type=int,   default=  2,        help='number of action variables')
    parser.add_argument('--z_dim',              type=int,   default=  2,        help='dimensions of latent variable')
    parser.add_argument('--sample_size',        type=int,   default=  10,       help='number of samples from z')

    parser.add_argument('--num_epochs',         type=int,   default= 50,        help='number of epochs')
    parser.add_argument('--learning_rate',      type=float, default= 0.004,     help='learning rate')
    parser.add_argument('--decay_rate',         type=float, default= 0.5,       help='decay rate for learning rate')
    parser.add_argument('--grad_clip',          type=float, default= 5.0,       help='clip gradients at this value')
    parser.add_argument('--save_h5',            type=bool,  default=False,      help='Whether to save network params to h5 file')

    parser.add_argument('--label_data',         type=bool,  default=False,      help='Just label the existing data with z-values.')
    parser.add_argument('--nonlinearity',       type= str, default="tanh")

    parser.add_argument('--train_mix',          type= int, default= 0)

    ###############################
    #          Encoder            #
    ###############################
    parser.add_argument('--encoder_size',          type=int,   default=128,        help='number of neurons in each LSTM layer')
    parser.add_argument('--num_encoder_layers',    type=int,   default=  2,        help='number of layers in the LSTM')
    parser.add_argument('--seq_length',            type=int,   default=50,        help='LSTM sequence length')

    ############################
    #       Policy Network     #
    ############################
    parser.add_argument('--policy_size',        type=int,   default=128,        help='number of neurons in each feedforward layer')
    parser.add_argument('--num_policy_layers',  type=int,   default=  2,        help='number of layers in the policy network')
    parser.add_argument('--recurrent',          type=bool,  default= False,     help='whether to use recurrent policy')
    parser.add_argument('--dropout_level',      type=float, default=  1.0,      help='percent of state values to keep')

    ############################
    #       Reconstructor      #
    ############################
    parser.add_argument('--rec_size',        type=int,   default= 64,        help='number of neurons in each feedforward layer')
    parser.add_argument('--num_rec_layers',  type=int,   default=  2,        help='number of layers in the policy network')
    parser.add_argument('--rec_weight',      type=float, default=  0.03,      help='weight applied to reconstruction cost')


    args = parser.parse_args()

    args.save_dir = ["./single_models", "./mix_models"][args.train_mix]

    # Construct model
    net = vae.VariationalAutoencoder(args)

    # Export model parameters or perform training
    if args.save_h5:
        data_loader = DataLoader(args.batch_size,
                args.seq_length, args.train_mix, DOMAINS)
        save_h5(args, net, data_loader)
    elif args.label_data:
        print("Labeling dataset with encoder.")
        label(args, net)
    else:
        train(args, net)

# Label dataset
def label(args, net):
    data_loader = DataLoader(args.batch_size, args.seq_length,
            args.train_mix, DOMAINS)
    with tf.Session() as sess:
        # Restore the model.
        tf.global_variables_initializer().run()
        saver = tf.train.Saver(tf.global_variables(), max_to_keep=5)
        Ws = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)
        Wt = Ws[0]

        # load the encoder
        if len(args.ckpt_name) > 0:
            print("Restoring model")
            saver.restore(sess, os.path.join(args.save_dir, args.ckpt_name))
        else:
            import pdb; pdb.set_trace()
#        else:
#            print("Loading Orig. h5 model")
#            load_h5(args, net)

        # go through dataset and label with z values.
        data_loader.reset_batchptr_train()
        policy_loss = 0.0

        from rllab.config import EXPERT_PATH
        data_paths = \
            ["{}/{}/".format(EXPERT_PATH,["juliaTrack_single","juliaTrack_mix"][0]),
            "{}/{}/".format(EXPERT_PATH,["juliaTrack_single","juliaTrack_mix"][1])]

        for dataset in ["train", "valid"]:
            for data_path in data_paths:
                with h5py.File("{}/{}/{}".format(data_path, dataset,"expert_trajs.h5"),'r') as hf:
                    obs_B_T_Do = hf["obs_B_T_Do"][...]
                    act_B_T_Da = hf["a_B_T_Da"][...]

                B, T, _ = obs_B_T_Do.shape
                print("B is: {}".format(B))
                assert B % args.batch_size == 0
                states, actions = [], []
                z_means, z_logstds = [], []
                for b in range(0,B,args.batch_size):
                    s = obs_B_T_Do[b:b+args.batch_size]
                    a = act_B_T_Da[b:b+args.batch_size]
                    z_mean, z_logstd, stat = net.encode(sess, s, a, args)

                    states.append(s)
                    actions.append(a)

                    z_means.append(z_mean)
                    z_logstds.append(z_logstd)

                with h5py.File("{}/{}/{}_vae_trajs.h5".format(data_path,
                        dataset,["single","mix"][args.train_mix]),'w') as hf:
                    hf["obs_B_T_Do"] = np.concatenate(states,axis=0)
                    hf["a_B_T_Da"] = np.concatenate(actions,axis=0)
                    hf["zmean_B_Dz"] = np.concatenate(z_means,axis=0)
                    hf["zlogstd_B_Dz"] = np.concatenate(z_logstds,axis=0)

        print("Wrote data")

# Train network
def train(args, net):
    data_loader = DataLoader(args.batch_size, args.seq_length,
            args.train_mix, DOMAINS)

    # Begin tf session
    with tf.Session() as sess:
        #Function to evaluate loss on validation set
        def val_loss():
            data_loader.reset_batchptr_val()
            policy_loss = 0.0
            for b in xrange(data_loader.n_batches_val):
                # Get batch of inputs/targets
                batch_dict = data_loader.next_batch_val()
                s = batch_dict["states"]
                a = batch_dict["actions"]
                _, _, state = net.encode(sess, s, a, args)

                # Set state and action input for encoder
                s_enc, a_enc = s[:,args.seq_length-1], a[:,args.seq_length-1]

                # Initialize the policy state
                if args.recurrent:
                    policy_state = []
                    for c, m in net.policy_state:
                        policy_state.append((c.eval(session= sess), m.eval(session= sess)))

                # Now loop over all timesteps, finding loss
                for t in xrange(args.seq_length):
                    # Get input and target values for specific time step (repeat values for multiple samples)
                    s_t, a_t = s[:,t], a[:,t]
                    s_t_rep = np.reshape(np.repeat(s_t, args.sample_size, axis=0), [args.batch_size, args.sample_size, args.state_dim])
                    a_t_rep = np.reshape(np.repeat(a_t, args.sample_size, axis=0), [args.batch_size, args.sample_size, args.action_dim])

                    # Construct inputs to network
                    feed_in = {}
                    feed_in[net.states_encode] = s_enc
                    feed_in[net.actions_encode] = a_enc
                    feed_in[net.states] = s_t_rep
                    feed_in[net.actions] = a_t_rep
                    feed_in[net.kl_weight] = 0.01
                    for i, (c, m) in enumerate(net.lstm_state):
                        feed_in[c], feed_in[m] = state[i]

                    if args.recurrent:
                        for i, (c, m) in enumerate(net.policy_state):
                            feed_in[c], feed_in[m] = policy_state[i]

                        feed_out = [net.policy_cost]
                        for c, m in net.final_policy_state:
                            feed_out.append(c)
                            feed_out.append(m)
                    else:
                        feed_out = net.policy_cost
                    out = sess.run(feed_out, feed_in)
                    if args.recurrent:
                        cost = out[0]
                        state_flat = out[1:]
                        policy_state = [state_flat[i:i+2] for i in range(0, len(state_flat), 2)]
                    else:
                        cost  = out
                    policy_loss += cost

            # Create new map of latent space
            return policy_loss/data_loader.n_batches_val

        tf.global_variables_initializer().run()
        saver = tf.train.Saver(tf.global_variables(), max_to_keep=5)

        # load from previous save
        if len(args.ckpt_name) > 0:
            saver.restore(sess, os.path.join(args.save_dir, args.ckpt_name))

        # Initialize variable to track validation score over time
        old_score = 1e6
        count_decay = 0
        decay_epochs = []

        # Initialize loss
        loss = 0.0
        policy_loss = 0.0
        rec_loss = 0.0

        # Set initial learning rate and weight on kl divergence
        print 'setting learning rate to ', args.learning_rate
        sess.run(tf.assign(net.learning_rate, args.learning_rate))
        kl_weight = args.min_kl_weight

        # Set up tensorboard summary
        merged = tf.summary.merge_all()
        writer = tf.summary.FileWriter('summaries/')

        losses = []
        policy_losses = []
        rec_losses = []
        # Loop over epochs
        for e in xrange(args.num_epochs):

            # Evaluate loss on validation set
            score = val_loss()
            print('Validation Loss: {0:f}'.format(score))

            # Create plot of latent space
            latent_viz_mixed(args, net, e, sess, data_loader)

            # Set learning rate
            if (old_score - score) < 0.01 and kl_weight >= 0.005:
                count_decay += 1
                decay_epochs.append(e)
                if len(decay_epochs) >= 3 and np.sum(np.diff(decay_epochs)[-2:]) == 2: break
                print 'setting learning rate to ', args.learning_rate * (args.decay_rate ** count_decay)
                sess.run(tf.assign(net.learning_rate, args.learning_rate * (args.decay_rate ** count_decay)))
            old_score = score

            data_loader.reset_batchptr_train()

            # Loop over batches
            for b in xrange(data_loader.n_batches_train):
                start = time.time()

                # Get batch of inputs/targets
                batch_dict = data_loader.next_batch_train()
                s = batch_dict["states"]
                a = batch_dict["actions"]
                _, _, state = net.encode(sess, s, a, args)

                # Set state and action input for encoder
                s_enc, a_enc = s[:,args.seq_length-1], a[:,args.seq_length-1,:args.action_dim]

                # Initialize the policy state
                if args.recurrent:
                    policy_state = []
                    for c, m in net.policy_state:
                        policy_state.append((c.eval(session= sess), m.eval(session= sess)))

                # Now loop over all timesteps, finding loss
                for t in xrange(args.seq_length):
                    # Get input and target values for specific time step (repeat values for multiple samples)
                    s_t, a_t = s[:,t], a[:,t]
                    s_t_rep = np.reshape(np.repeat(s_t, args.sample_size, axis=0), [args.batch_size, args.sample_size, args.state_dim])
                    a_t_rep = np.reshape(np.repeat(a_t, args.sample_size, axis=0), [args.batch_size, args.sample_size, args.action_dim])

                    # Construct inputs to network
                    feed_in = {}
                    feed_in[net.states_encode] = s_enc
                    feed_in[net.actions_encode] = a_enc
                    feed_in[net.states] = s_t_rep
                    feed_in[net.actions] = a_t_rep
                    feed_in[net.kl_weight] = kl_weight
                    for i, (c, m) in enumerate(net.lstm_state):
                        feed_in[c], feed_in[m] = state[i]

                    if args.recurrent:
                        for i, (c, m) in enumerate(net.policy_state):
                            feed_in[c], feed_in[m] = policy_state[i]
                    feed_out = [net.cost, net.policy_cost, net.rec_cost, net.train]
                    if args.recurrent:
                        for c, m in net.final_policy_state:
                            feed_out.append(c)
                            feed_out.append(m)

                    out = sess.run(feed_out, feed_in)
                    train_loss = out[0]
                    policy_cost = out[1]
                    rec_cost = out[2]
                    if args.recurrent:
                        state_flat = out[4:]
                        policy_state = [state_flat[i:i+2] for i in range(0, len(state_flat), 2)]


                    policy_loss += policy_cost
                    rec_loss += rec_cost
                    loss += train_loss

                end = time.time()

                # Print loss
                if (e * data_loader.n_batches_train + b) % 10 == 0 and b > 0:
                    print("kl weight: {}".format(kl_weight))
                    print "{}/{} (epoch {}), train_loss = {:.3f}, time/batch = {:.3f}" \
                      .format(e * data_loader.n_batches_train + b,
                              args.num_epochs * data_loader.n_batches_train,
                              e, loss/10., end - start)
                    print "{}/{} (epoch {}), policy_loss = {:.3f}, time/batch = {:.3f}" \
                      .format(e * data_loader.n_batches_train + b,
                              args.num_epochs * data_loader.n_batches_train,
                              e, policy_loss/10., end - start)
                    print "{}/{} (epoch {}), rec_loss = {:.3f}, time/batch = {:.3f}" \
                      .format(e * data_loader.n_batches_train + b,
                              args.num_epochs * data_loader.n_batches_train,
                              e, rec_loss/10., end - start)

                    losses.append(loss)
                    policy_losses.append(policy_loss)
                    rec_losses.append(rec_loss)

                    loss = 0.0
                    policy_loss = 0.0
                    rec_loss = 0.0
                kl_weight = min(args.max_kl_weight, kl_weight*1.05**(args.seq_length/300.))

            # Save model every epoch
            checkpoint_path = os.path.join(args.save_dir, 'vae_3.ckpt')
            saver.save(sess, checkpoint_path, global_step = e)
            print "model saved to {}".format(checkpoint_path)

    plt.plot(np.arange(len(losses)), np.column_stack([losses,
        policy_losses, rec_losses]))
    plt.show()


if __name__ == '__main__':
    main()
