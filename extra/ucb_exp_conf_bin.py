import numpy as np
import pandas as pd
import itertools, argparse
from tqdm import tqdm
import os, sys, random
from statistics import mode

def compute_reward(conf_branch, arm, delta_conf, overhead):
	return 0 if (conf_branch >= arm) else delta_conf - overhead


def get_row_data(row, threshold):
	conf_branch = row.conf_branch_1.item()
	conf_final = row.conf_branch_2.item()
	return conf_branch, conf_final-conf_branch
	if(conf_final >= threshold):
		delta_conf = conf_final - conf_branch
		return conf_branch, delta_conf
	else:
		conf_list = [conf_branch, conf_final]
		delta_conf = max(conf_list) - conf_branch 
		return conf_branch, delta_conf

def run_ucb(df, label, threshold_list, overhead, n_rounds, c, bin_lower, bin_upper, verbose):

	df = df.sample(frac=1)
	delta = 1e-10

	avg_reward_actions, n_actions = np.zeros(len(threshold_list)), np.zeros(len(threshold_list))
	reward_actions = [[] for i in range(len(threshold_list))]
	cum_regret, t = 0, 0
	inst_regret_list, selected_arm_list = [], []

	for n_round in tqdm(range(n_rounds)):
		idx = random.choice(np.arange(len(df)))
		row = df.iloc[[idx]]

		if (t < len(threshold_list)):
			action = t
		else:
			q = avg_reward_actions + c*np.sqrt(np.log(t)/(n_actions+delta))
			action = np.argmax(q)

		threshold = threshold_list[action]

		conf_branch, delta_conf = get_row_data(row, threshold)
		reward = compute_reward(conf_branch, threshold, delta_conf, overhead)

		n_actions[action] += 1
		t += 1

		reward_actions[action].append(reward)

		avg_reward_actions = np.array([sum(reward_actions[i])/n_actions[i] for i in range(len(threshold_list))])
		optimal_reward = max(0, delta_conf - overhead)

		inst_regret = optimal_reward - reward

		inst_regret_list.append(inst_regret)
		selected_arm_list.append(threshold)

	result = {"selected_arm": selected_arm_list, "regret": inst_regret_list, 
	"label":[label]*len(inst_regret_list), "overhead":[round(overhead, 2)]*len(inst_regret_list),
	"bin_lower": [round(bin_lower, 2)]*len(inst_regret_list), "bin_upper": [round(bin_upper, 2)]*len(inst_regret_list)}

	return result


def ucb_experiment(df, threshold_list, overhead_list, label_list, n_round, c, savePath, verbose=False):
	df_result = pd.DataFrame()

	config_list = list(itertools.product(*[label_list, overhead_list]))    

	bin_boundaries = np.arange(0.5, 1.1, 0.1)
	bin_lowers = bin_boundaries[:-1]
	bin_uppers = bin_boundaries[1:]

	for label, overhead in tqdm(config_list):
		for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):

			df_temp = df[(df.conf_branch_1 >= bin_lower) & (df.conf_branch_1 <= bin_upper) & (df.label==label)] 
			
			if(len(df_temp.conf_branch_1.values) > 0):
				result = run_ucb(df_temp, label, threshold_list, overhead, n_round, c, bin_lower, bin_upper, verbose)
				df2 = pd.DataFrame(np.array(list(result.values())).T, columns=list(result.keys()))
				df_result = df_result.append(df2)
				df_result.to_csv(savePath)

if __name__ == "__main__":

	parser = argparse.ArgumentParser(description='UCB using Alexnet')
	parser.add_argument('--model_id', type=int, default=2, help='Model Id (default: 2)')
	parser.add_argument('--c', type=int, default=1.0, help='Parameter c (default: 1.0)')
	parser.add_argument('--n_rounds', type=int, default=100000, help='Model Id (default: 100000)')

	args = parser.parse_args()

	root_path = os.path.join(".")
	results_path = os.path.join(root_path, "inference_exp_ucb_%s.csv"%(args.model_id))
	df_result = pd.read_csv(results_path)
	df_result = df_result.loc[:, ~df_result.columns.str.contains('^Unnamed')]
	threshold_list = np.arange(0, 1.1, 0.1)
	overhead_list = np.arange(0, 1.1, 0.1)
	verbose = False
	label_list = ["cat", "ship", "dog", "automobile"]
	savePath = os.path.join(".", "ucb_result_c_%s_temp.csv"%(args.c))

	ucb_experiment(df_result, threshold_list, overhead_list, label_list, args.n_rounds, args.c, savePath, verbose)



