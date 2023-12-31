import os
os.environ["CUDA_VISIBLE_DEVICES"]="4,5,6,7"
# from kilt import kilt_utils as utils
# from kilt.retrievers import DPR_connector
import utils
from rouge_score import rouge_scorer
import random
import numpy as np
import torch
import argparse
torch.set_grad_enabled(False)
from pac_utils import find_maximum_train_error_allow
import time
import pickle
import json
import tasks
from skopt.space import Real
from skopt import gp_minimize
from skopt.utils import use_named_args
import multiprocessing
from multiprocessing import Value
from tqdm import tqdm

def write_list(a_list, file_name):
    # store list in binary file so 'wb' mode
    with open(file_name, 'wb') as fp:
        pickle.dump(a_list, fp)
        print('Done writing list into a binary file')
def read_list(file_name):
    # for reading also binary mode is important
    with open(file_name, 'rb') as fp:
        n_list = pickle.load(fp)
        return n_list

import pickle
def write_list(a_list, file_name):
    # store list in binary file so 'wb' mode
    with open(file_name, 'wb') as fp:
        pickle.dump(a_list, fp)
        print('Done writing list into a binary file')
def read_list(file_name):
    # for reading also binary mode is important
    with open(file_name, 'rb') as fp:
        n_list = pickle.load(fp)
        return n_list

def save_results(task):
    # save retrieved_scores to a pickle file
    write_list(retrieved_scores, f'retrieved_scores_{task}.p')
    # save retrieved_true_scores to a pickle file
    write_list(retrieved_true_scores, f'retrieved_true_scores_{task}.p')
    # save queries to a pickle file
    write_list(queries, f'queries_{task}.p')
    # save answers to a pickle file
    write_list(answers, f'answers_{task}.p')
    # save passages to a pickle file
    write_list(passages, f'passages_{task}.p')
    # save opensource_true_scores to a pickle file
    write_list(opensource_true_scores, f'opensource_true_scores_{task}.p')
    # save opensource_texts to a ickle file
#     write_list(opensource_texts, f'opensource_texts_{task}.p')
    # save opensource_answers to a pickle file
    write_list(opensource_answers, f'opensource_answers_{task}.p')
    # save opensource_semantics to a picle file
    write_list(opensource_semantics, f'opensource_semantics_{task}.p')
    # save feasibilities to a pickle file
    write_list(feasibilities, f'feasibilities_{task}.p')
    # save occurances to a pickle file
    write_list(occurances, f'occurances_{task}.p')
    # save semantic_ids to a pickle file
    write_list(semantic_ids, f'semantic_ids_{task}.p')

def read_results(task, end=1000):
    retrieved_scores = read_list(f'retrieved_scores_{task}.p')[:end]
    retrieved_true_scores = read_list(f'retrieved_true_scores_{task}.p')[:end]
    queries = read_list(f'queries_{task}.p')[:end]
    answers = read_list(f'answers_{task}.p')[:end]
    opensource_true_scores = read_list(f'opensource_true_scores_{task}.p')[:end]
    opensource_answers = read_list(f'opensource_answers_{task}.p')[:end]
    opensource_semantics = read_list(f'opensource_semantics_{task}.p')[:end]
    opensource_occurances = read_list(f'occurances_{task}.p')[:end]
    opensource_semantic_ids = read_list(f'semantic_ids_{task}.p')[:end]
    opensource_probs = read_list(f'probs_{task}.p')[:end]
    
    return retrieved_scores, retrieved_true_scores, \
           queries, answers, \
           opensource_true_scores, opensource_answers, \
           opensource_occurances, opensource_semantic_ids, opensource_probs

def coverage(
        retrieved_true_scores_list, opensource_true_scores_list,
        retrieved_thr, qa_thr):

    includes = []
    for idx, (retrieved_true_score, opensource_true_score) in enumerate(zip(retrieved_true_scores_list, opensource_true_scores_list)):
#         if idx > 20:
        opensource_true_score = np.max(opensource_true_score)
        include = True if (retrieved_true_score >= retrieved_thr and 
                        opensource_true_score >= qa_thr) \
                    else False
        includes.append(include)
    return includes


def evaluate(
        test_retrieved_scores,
        test_queries, test_answers, test_opensource_answers, 
        test_opensource_semantic_ids, test_opensource_probs,
        retrieved_thr, opensource_qa_thr,
        cluster=True, kernel=40, verbose=True):
    
    length = len(test_retrieved_scores)
    lens = np.linspace(0, length, kernel+1)
    test_retrieved_scores_list = [test_retrieved_scores[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    test_opensource_semantic_ids_list = [test_opensource_semantic_ids[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    test_opensource_probs_list = [test_opensource_probs[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    test_answers_list = [test_answers[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    
    def run(i, shared_includes, shared_semantic_counts):
        includes = []
        semantics_total = []
        coverages = []
        semantic_counts = []
        for idx, (retrieved_scores_tmp, answers_tmp,\
                opensource_semantic_ids_tmp, opensource_probs_tmp) \
            in tqdm(enumerate(zip(
                test_retrieved_scores_list[i], test_answers_list[i], \
                test_opensource_semantic_ids_list[i], test_opensource_probs_list[i])), total=len(test_retrieved_scores_list[i])):

            include = False
    #         coverage_tmp = coverage(retrieved_true_scores_tmp, 
    #                         [opensource_true_scores_tmp],
    #                         retrieved_thr,
    #                         opensource_qa_thr
    #                        )[0]
    #         coverages.append(coverage_tmp)
            retrieved_count = 0
            semantics = []
            for retrieved_score, semantic_set_ids, probs in zip(retrieved_scores_tmp, opensource_semantic_ids_tmp, opensource_probs_tmp):
                    if retrieved_score < retrieved_thr:
                        continue
                    else:
                        retrieved_count += 1
                        for predicted_answer in semantic_set_ids.keys():
                            concept_id = semantic_set_ids[predicted_answer]
                            prob = probs[concept_id]
                            if prob >= opensource_qa_thr:
                                semantics.append(predicted_answer)

                                # TODO: check if the semantic is consistent with true answer
                                if include is False:
                                    for answer_tmp in answers_tmp:
                                        scores = scorer.score(answer_tmp,
                                                              predicted_answer)
                                        scores = scores['rouge1'][2]
                                        if scores >= 0.3:
                                            include = True
                                            break
            if cluster:
                semantic_set_ids, semantic_probs, item_occurance = \
                            utils.clustering(semantics, "", scorer=scorer)
                semantic_counts.append(len(semantic_probs.keys()))
            else:
                semantic_counts.append(len(semantics))
            semantics_total.append(semantic_set_ids)
    #         answer_counts.append(retrieved_count)
            includes.append(include)
        shared_includes.value += np.sum(includes)
        shared_semantic_counts.value += np.sum(semantic_counts)
    
    processes = []
    shared_includes = Value('f', 0.0)
    shared_semantic_counts = Value('f', 0.0)

    for i in range(0, kernel):
        p = multiprocessing.Process(target=run, args=(i, shared_includes, shared_semantic_counts))
        processes.append(p)
        p.start()

    for process in processes:
        process.join()
        
    return shared_includes.value/length, 0.0, shared_semantic_counts.value/length

def evaluate_vanila(
        test_retrieved_scores,
        test_queries, test_answers, test_opensource_answers, 
        test_opensource_semantic_ids, test_opensource_probs,
        cluster=True, kernel=40, verbose=True):
    
    length = len(test_retrieved_scores)
    lens = np.linspace(0, length, kernel+1)
    test_retrieved_scores_list = [test_retrieved_scores[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    test_opensource_semantic_ids_list = [test_opensource_semantic_ids[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    test_opensource_probs_list = [test_opensource_probs[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    test_answers_list = [test_answers[int(lens[i]):int(lens[i+1])] for i in range(kernel)]
    
    def run(i, shared_includes, shared_semantic_counts):
        includes = []
        semantics_total = []
        coverages = []
        semantic_counts = []
        for idx, (retrieved_scores_tmp, answers_tmp,\
                opensource_semantic_ids_tmp, opensource_probs_tmp) \
            in tqdm(enumerate(zip(
                test_retrieved_scores_list[i], test_answers_list[i], \
                test_opensource_semantic_ids_list[i], test_opensource_probs_list[i])), total=len(test_retrieved_scores_list[i])):

            include = False
    #         coverage_tmp = coverage(retrieved_true_scores_tmp, 
    #                         [opensource_true_scores_tmp],
    #                         retrieved_thr,
    #                         opensource_qa_thr
    #                        )[0]
    #         coverages.append(coverage_tmp)
            retrieved_count = 0
            semantics = []
            for retrieved_score, semantic_set_ids, probs in zip(retrieved_scores_tmp, opensource_semantic_ids_tmp, opensource_probs_tmp):
                retrieved_count += 1
                for predicted_answer in semantic_set_ids.keys():
                    concept_id = semantic_set_ids[predicted_answer]
                    prob = probs[concept_id]
                    semantics.append(predicted_answer)

                    # TODO: check if the semantic is consistent with true answer
                    if include is False:
                        for answer_tmp in answers_tmp:
                            scores = scorer.score(answer_tmp,
                                                  predicted_answer)
                            scores = scores['rouge1'][2]
                            if scores >= 0.3:
                                include = True
                                break
                break
            if cluster:
                semantic_set_ids, semantic_probs, item_occurance = \
                            utils.clustering(semantics, "", scorer=scorer)
                semantic_counts.append(len(semantic_probs.keys()))
            else:
                semantic_counts.append(len(semantics))
            semantics_total.append(semantic_set_ids)
    #         answer_counts.append(retrieved_count)
            includes.append(include)
        shared_includes.value += np.sum(includes)
        shared_semantic_counts.value += np.sum(semantic_counts)
    
    processes = []
    shared_includes = Value('f', 0.0)
    shared_semantic_counts = Value('f', 0.0)

    for i in range(0, kernel):
        p = multiprocessing.Process(target=run, args=(i, shared_includes, shared_semantic_counts))
        processes.append(p)
        p.start()

    for process in processes:
        process.join()
        
    return shared_includes.value/length, 0.0, shared_semantic_counts.value/length


def softmax(vec):
    nom = np.exp(vec - np.mean(vec))
    return nom / np.sum(nom)


"""
Weight HMP module
"""
w1 = Real(name='w1', low=0.0, high=1.0)
w2 = Real(name='w2', low=0.0, high=1.0)

# Gather the search-space dimensions in a list.
dimensions = [w1, w2]

@use_named_args(dimensions=dimensions)
def objective(w1, w2):
    weights = softmax(np.array([w1, w2])).reshape(-1, 1)
    alpha_retrieve = alpha * weights[0]
    alpha_qa = alpha * weights[1]
    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=alpha_retrieve)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=alpha_qa)
    results = evaluate(cal_second_retrieved_scores, cal_second_queries, \
                       cal_second_answers, cal_second_opensource_answers, \
                       cal_second_opensource_semantic_ids, cal_second_opensource_probs, \
                       retrieved_thr, opensource_qa_thr,
                       cluster=True
                      )
    coverage = np.mean(results[0])
    average_answer = np.mean(results[1])
    average_semantic = np.mean(results[2])
    return average_semantic

@use_named_args(dimensions=dimensions)
def objective_pac(w1, w2):
    weights = softmax(np.array([w1, w2])).reshape(-1, 1)
    alpha_retrieve = alpha * weights[0]
    alpha_qa = alpha * weights[1]
    alpha_retrieve_pac = find_maximum_train_error_allow(alpha_retrieve, delta/2.0, len(cal_first_indices))
    alpha_qa_pac = find_maximum_train_error_allow(alpha_qa, delta/2.0, len(cal_first_indices))

    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=alpha_retrieve_pac)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=alpha_qa_pac)
    results = evaluate(cal_second_retrieved_scores, cal_second_queries, 
                       cal_second_answers, cal_second_opensource_answers, \
                       cal_second_opensource_semantic_ids, cal_second_opensource_probs, 
                       retrieved_thr, opensource_qa_thr, 
                       cluster=True)
    coverage = np.mean(results[0])
    average_answer = np.mean(results[1])
    average_semantic = np.mean(results[2])
    return average_semantic

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=str, default='nq')
    parser.add_argument('--alpha', type=float, default=0.2)
    parser.add_argument('--semantic', type=bool, default=False)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()

    np.random.seed(args.seed)
    random.seed(args.seed)
    start = time.time()
    results_dict = {}
    alpha = args.alpha

    print("****************************")
    print(f'Task={args.task}, alpha={args.alpha}, seed={args.seed}, semantic={args.semantic}')
    print("****************************")
    results_dict["task"] = args.task
    results_dict["alpha"] = args.alpha
    results_dict["seed"] = args.seed
    results_dict["semantic"] = args.semantic
    alpha = args.alpha
    seed = args.seed
    task = args.task
    semantic = args.semantic


    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"],
                                            use_stemmer=True)
    if args.semantic:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        # setup semantic model
        semantic_tokenizer = \
            AutoTokenizer.from_pretrained("microsoft/deberta-large-mnli")
        semantic_model = \
            AutoModelForSequenceClassification.from_pretrained(
                "microsoft/deberta-large-mnli"
            ).cuda()

    retrieved_scores, retrieved_true_scores, queries, answers, opensource_true_scores, opensource_answers, opensource_occurances, opensource_semantic_ids, opensource_probs = \
        read_results(task, end=1000)
    # dataset_dpr = tasks.RQA_dpr(task=args.task)
    # elements = dataset_dpr.elements
    # all_queries = [element['question'] for element in elements]
    # answers = []
    # for query in queries:
    #     idx = all_queries.index(query)
    #     answers.append(elements[idx]['answers'])
    # answers_semantic = []
    # probs_semantic = []
    # for idx_tmp, [true_score, scores, returned_answers] in enumerate(zip(retrieved_true_scores, retrieved_scores, opensource_answers)):
    #     idx = list(scores).index(true_score)
    #     tmp = returned_answers[idx]
    #     answers_semantic.append(tmp)
    

    indices = np.arange(len(retrieved_true_scores))
    random.shuffle(indices)
    cal_first_indices = indices[:int(len(indices) * 0.3)]
    cal_second_indices = indices[int(len(indices) * 0.3) : int(len(indices) * 0.6)]
    test_indices = indices[int(len(indices) * 0.6):]

    # indices = np.arange(1000)
    indices = np.arange(len(queries))
    random.shuffle(indices)
    cal_first_indices = indices[:int(len(indices) * 0.3)]
    cal_second_indices = indices[int(len(indices) * 0.3) : int(len(indices) * 0.6)]
    test_indices = indices[int(len(indices) * 0.6):]
    # test_indices = indices[int(len(indices) * 0.3):]

    # indices = np.arange(1000)
    indices = np.arange(len(queries))
    random.shuffle(indices)
    cal_first_indices = indices[:int(len(indices) * 0.3)]
    cal_second_indices = indices[int(len(indices) * 0.3) : int(len(indices) * 0.6)]
    test_indices = indices[int(len(indices) * 0.6):]
    # test_indices = indices[int(len(indices) * 0.3):]

    cal_first_retrieved_true_scores = utils.split(retrieved_true_scores, cal_first_indices)
    cal_second_retrieved_true_scores = utils.split(retrieved_true_scores, cal_second_indices)
    test_retrieved_true_scores = utils.split(retrieved_true_scores, test_indices)
    cal_first_opensource_true_scores = utils.split(opensource_true_scores, cal_first_indices)
    cal_second_opensource_true_scores = utils.split(opensource_true_scores, cal_second_indices)
    test_opensource_true_scores = utils.split(opensource_true_scores, test_indices)
    cal_first_retrieved_scores = utils.split(retrieved_scores, cal_first_indices)
    cal_second_retrieved_scores = utils.split(retrieved_scores, cal_second_indices)
    test_retrieved_scores = utils.split(retrieved_scores, test_indices)
    cal_first_opensource_occurances = utils.split(opensource_occurances, cal_first_indices)
    cal_second_opensource_occurances = utils.split(opensource_occurances, cal_second_indices)
    test_opensource_occurances = utils.split(opensource_occurances, test_indices)
    cal_first_opensource_semantic_ids = utils.split(opensource_semantic_ids, cal_first_indices)
    cal_second_opensource_semantic_ids = utils.split(opensource_semantic_ids, cal_second_indices)
    test_opensource_semantic_ids = utils.split(opensource_semantic_ids, test_indices)
    cal_first_queries = utils.split(queries, cal_first_indices)
    cal_second_queries = utils.split(queries, cal_second_indices)
    test_queries = utils.split(queries, test_indices)
    cal_first_opensource_answers = utils.split(opensource_answers, cal_first_indices)
    cal_second_opensource_answers = utils.split(opensource_answers, cal_second_indices)
    test_opensource_answers = utils.split(opensource_answers, test_indices)
    cal_first_answers = utils.split(answers, cal_first_indices)
    cal_second_answers = utils.split(answers, cal_second_indices)
    test_answers = utils.split(answers, test_indices)
    cal_first_opensource_probs = utils.split(opensource_probs, cal_first_indices)
    cal_second_opensource_probs = utils.split(opensource_probs, cal_second_indices)
    test_opensource_probs = utils.split(opensource_probs, test_indices)

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"],
                                       use_stemmer=True)

    print("Individual components")
    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=args.alpha/2)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=args.alpha/2)

    retrieved_coverage = np.mean(np.array(cal_second_retrieved_true_scores) >= retrieved_thr)
    cal_second_scores = []
    for scores in cal_second_opensource_true_scores:
        cal_second_scores.append(np.max(scores))
    qa_coverage = np.mean(np.array(cal_second_scores) >= opensource_qa_thr)
    print('retrieval coverage', retrieved_coverage)
    print('qa coverage', qa_coverage)

    retrieved_coverage = np.mean(np.array(test_retrieved_true_scores) >= retrieved_thr)
    test_scores = []
    for scores in test_opensource_true_scores:
        test_scores.append(np.max(scores))
    qa_coverage = np.mean(np.array(test_scores) >= opensource_qa_thr)
    print('test retrieval coverage', retrieved_coverage)
    print('test qa coverage', qa_coverage)

    results_dict["retrieval_coverage"] = retrieved_coverage
    results_dict["qa_coverage"] = qa_coverage

    coverages = coverage(test_retrieved_true_scores, 
        test_opensource_true_scores,
        retrieved_thr,
        opensource_qa_thr
        )
    print('End-to-end coverage', np.mean(coverages))
    results_dict["end_to_end_coverage"] = np.mean(coverages)

    print("Individual compponents with PAC")
    delta = 0.1
    retrieve_alpha = find_maximum_train_error_allow(args.alpha/2.0, delta/2.0, len(cal_first_indices))
    qa_alpha = find_maximum_train_error_allow(args.alpha/2.0, delta/2.0, len(cal_first_indices))
    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=retrieve_alpha)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=qa_alpha)

    retrieved_coverage = np.mean(np.array(cal_second_retrieved_true_scores) >= retrieved_thr)
    cal_second_scores = []
    for scores in cal_second_opensource_true_scores:
        cal_second_scores.append(np.max(scores))
    qa_coverage = np.mean(np.array(cal_second_scores) >= opensource_qa_thr)
    print('retrieval coverage', retrieved_coverage)
    print('qa coverage', qa_coverage)

    retrieved_coverage = np.mean(np.array(test_retrieved_true_scores) >= retrieved_thr)
    test_scores = []
    for scores in test_opensource_true_scores:
        test_scores.append(np.max(scores))
    qa_coverage = np.mean(np.array(test_scores) >= opensource_qa_thr)
    print('test retrieval coverage', retrieved_coverage)
    print('test qa coverage', qa_coverage)

    coverages = coverage(
        test_retrieved_true_scores, 
        test_opensource_true_scores,
        retrieved_thr,
        opensource_qa_thr
        )
    print('End-to-end coverage', np.mean(coverages))

    results_dict["retrieval_coverage_pac"] = retrieved_coverage
    results_dict["qa_coverage_pac"] = qa_coverage
    results_dict["end_to_end_coverage_pac"] = np.mean(coverages)

    """
    Weight Bonf module
    """
    result = gp_minimize(
        func=objective,
        dimensions=dimensions,
        acq_func="EI",      # the acquisition function
        n_calls=15,
        random_state=args.seed,
        verbose=False,
        x0=[[1, 1]])

    print("Best fitness:", result.fun)
    print("Best parameters:", softmax(result.x))

    weights = softmax(result.x).reshape(-1, 1)
    alpha_retrieve = alpha * weights[0]
    alpha_qa = alpha * weights[1]
    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=alpha_retrieve)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=alpha_qa)
    results = evaluate(
        test_retrieved_scores, test_queries,
        test_answers, test_opensource_answers, 
        test_opensource_semantic_ids, test_opensource_probs,
        retrieved_thr, opensource_qa_thr,
        cluster=True
    )

    print('TRAC')
    print('Desired coverage rate', 1-args.alpha)
    print('Coverage', np.mean(results[0]))
    # print('Average answer', np.mean(results[1]))
    print('Average semantic', np.mean(results[2]))

    results_dict["TRAC_coverage"] = np.mean(results[0])
    results_dict["TRAC_average_semantic"] = np.mean(results[2])

    alpha_retrieve = alpha * (1/2.0)
    alpha_qa = alpha * (1/2.0)
    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=alpha_retrieve)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=alpha_qa)
    results = evaluate(
        test_retrieved_scores, test_queries,
        test_answers, test_opensource_answers, 
        test_opensource_semantic_ids, test_opensource_probs,
        retrieved_thr, opensource_qa_thr,
        cluster=True
    )
    print('Bonf')
    print('Desired coverage rate', 1-args.alpha)
    print('Coverage', np.mean(results[0]))
    # print('Average answer', np.mean(results[1]))
    print('Average semantic', np.mean(results[2]))

    results_dict["Bonf_coverage"] = np.mean(results[0])
    results_dict["Bonf_average_semantic"] = np.mean(results[2])

    alpha_retrieve = alpha * (1/2.0)
    alpha_qa = alpha * (1/2.0)

    delta = 0.1
    alpha_retrieve_pac = find_maximum_train_error_allow(alpha_retrieve, delta/2.0, len(cal_first_indices))
    alpha_qa_pac = find_maximum_train_error_allow(alpha_qa, delta/2.0, len(cal_first_indices))

    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=alpha_retrieve_pac)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=alpha_qa_pac)
    results = evaluate(
        test_retrieved_scores, test_queries,
        test_answers, test_opensource_answers, 
        test_opensource_semantic_ids, test_opensource_probs, 
        retrieved_thr, opensource_qa_thr)
    print('PAC-Bonf')
    print('Desired coverage rate', 1-args.alpha)
    print('Coverage', np.mean(results[0]))
    # print('Average answer', np.mean(results[1]))
    print('Average semantic', np.mean(results[2]))

    results_dict["PAC_Bonf_coverage"] = np.mean(results[0])
    # results_dict["PAC_Bonf_average_answer"] = np.mean(results[1])   
    results_dict["PAC_Bonf_average_semantic"] = np.mean(results[2])

    """
    Weight PAC-TRAC module
    """
    result = gp_minimize(
        func=objective_pac,
        dimensions=dimensions,
        acq_func="EI",      # the acquisition function
        n_calls=15,
        random_state=args.seed,
        verbose=False,
        x0=[[1, 1]])

    print("Best fitness:", result.fun)
    print("Best parameters:", softmax(result.x))

    weights = softmax(result.x).reshape(-1, 1)
    alpha_retrieve = alpha * weights[0]
    alpha_qa = alpha * weights[1]
    alpha_retrieve_pac = find_maximum_train_error_allow(alpha_retrieve, delta/2.0, len(cal_first_indices))
    alpha_qa_pac = find_maximum_train_error_allow(alpha_qa, delta/2.0, len(cal_first_indices))
    retrieved_thr = utils.compute_threshold(cal_first_retrieved_true_scores, alpha=alpha_retrieve_pac)
    cal_first_scores = []
    for scores in cal_first_opensource_true_scores:
        cal_first_scores.append(np.max(scores))
    opensource_qa_thr = utils.compute_threshold(cal_first_scores, alpha=alpha_qa_pac)
    results = evaluate(
        test_retrieved_scores, test_queries,
        test_answers, test_opensource_answers, 
        test_opensource_semantic_ids, test_opensource_probs, 
        retrieved_thr, opensource_qa_thr,
        cluster=True)

    print('PAC-TRAC')
    print('Desired coverage rate', 1-args.alpha)
    print('Coverage', np.mean(results[0]))
    # print('Average answer', np.mean(results[1]))
    print('Average semantic', np.mean(results[2]))

    results_dict["PAC_TRAC_coverage"] = np.mean(results[0])
    results_dict["PAC_TRAC_average_semantic"] = np.mean(results[2])

    results = evaluate_vanila(
        retrieved_scores, queries,
        answers, opensource_answers, 
        opensource_semantic_ids, opensource_probs, 
        cluster=True)
    
    print('Vanila')
    print('Desired coverage rate', 1-alpha)
    print('Coverage', np.mean(results[0]))
    # print('Average answer', np.mean(results[1]))
    print('Average semantic', np.mean(results[2]))
    results_dict["Vanila_coverage"] = np.mean(results[0])
    # results_dict["PAC_Bonf_average_answer"] = np.mean(results[1])   
    results_dict["Vanila_average_semantic"] = np.mean(results[2])

    print()
    print()

    with open("opensource_results_new.txt", "a") as f:
        json.dump(results_dict, f)
        f.write("\n")
