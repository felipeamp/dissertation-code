#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""Module containing all criteria available for tests."""

import abc
import collections
import itertools
import math

import cvxpy as cvx
import numpy as np
import scipy

import chol


#: Minimum gain allowed for Local Search methods to continue searching.
EPSILON = 0.000001

#: Maximum rank allowed for sigma_j matrices in Conditional Inferente Tree framework
BIG_CONTINGENCY_TABLE_THRESHOLD = 200

#: Contains the information about a given split. When empty, defaults to
#: `(None, [], float('-inf'))`.
Split = collections.namedtuple('Split',
                               ['attrib_index',
                                'splits_values',
                                'criterion_value'])
Split.__new__.__defaults__ = (None, [], float('-inf'))


class Criterion(object):
    """Abstract base class for every criterion.
    """
    __metaclass__ = abc.ABCMeta

    name = ''

    @classmethod
    @abc.abstractmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the criterion.
        """
        # returns (separation_attrib_index, splits_values, criterion_value)
        pass



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                       TWOING                                              ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class Twoing(Criterion):
    """Twoing criterion. For reference see "Breiman, L., Friedman, J. J., Olshen, R. A., and
    Stone, C. J. Classification and Regression Trees. Wadsworth, 1984".
    """
    name = 'Twoing'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the Twoing criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                best_total_gini_gain = float('-inf')
                best_left_values = set()
                best_right_values = set()
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                for (set_left_classes,
                     set_right_classes) in cls._generate_twoing(tree_node.class_index_num_samples):
                    (twoing_contingency_table,
                     superclass_index_num_samples) = cls._get_twoing_contingency_table(
                         tree_node.contingency_tables[attrib_index].contingency_table,
                         tree_node.contingency_tables[attrib_index].values_num_samples,
                         set_left_classes,
                         set_right_classes)
                    original_gini = cls._calculate_gini_index(len(tree_node.valid_samples_indices),
                                                              superclass_index_num_samples)
                    (curr_gini_gain,
                     left_values,
                     right_values) = cls._two_class_trick(
                         original_gini,
                         superclass_index_num_samples,
                         values_seen,
                         tree_node.contingency_tables[attrib_index].values_num_samples,
                         twoing_contingency_table,
                         len(tree_node.valid_samples_indices))
                    if curr_gini_gain > best_total_gini_gain:
                        best_total_gini_gain = curr_gini_gain
                        best_left_values = left_values
                        best_right_values = right_values

                num_values, num_classes = tree_node.contingency_tables[
                    attrib_index].contingency_table.shape
                class_num_left = np.zeros((num_classes), dtype=int)
                class_num_right = np.zeros((num_classes), dtype=int)
                num_left_samples = 0
                num_right_samples = 0
                for value in range(num_values):
                    if value in best_left_values:
                        class_num_left += tree_node.contingency_tables[
                            attrib_index].contingency_table[value, :]
                        num_left_samples += tree_node.contingency_tables[
                            attrib_index].values_num_samples[value]
                    else:
                        class_num_right += tree_node.contingency_tables[
                            attrib_index].contingency_table[value, :]
                        num_right_samples += tree_node.contingency_tables[
                            attrib_index].values_num_samples[value]
                twoing_value = cls._get_twoing_value(
                    class_num_left, class_num_right, num_left_samples, num_right_samples)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[best_left_values, best_right_values],
                          criterion_value=twoing_value))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_twoing,
                 last_left_value,
                 first_right_value) = cls._twoing_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_twoing))
        if best_splits_per_attrib:
            return max(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @staticmethod
    def _generate_twoing(class_index_num_samples):
        # We only need to look at superclasses of up to (len(class_index_num_samples)/2 + 1)
        # elements because of symmetry! The subsets we are not choosing are complements of the ones
        # chosen.
        non_empty_classes = set([])
        for class_index, class_num_samples in enumerate(class_index_num_samples):
            if class_num_samples > 0:
                non_empty_classes.add(class_index)
        number_non_empty_classes = len(non_empty_classes)

        for left_classes in itertools.chain.from_iterable(
                itertools.combinations(non_empty_classes, size_left_superclass)
                for size_left_superclass in range(1, number_non_empty_classes // 2 + 1)):
            set_left_classes = set(left_classes)
            set_right_classes = non_empty_classes - set_left_classes
            if not set_left_classes or not set_right_classes:
                # A valid split must have at least one sample in each side
                continue
            yield set_left_classes, set_right_classes

    @staticmethod
    def _get_twoing_contingency_table(contingency_table, values_num_samples, set_left_classes,
                                      set_right_classes):
        twoing_contingency_table = np.zeros((contingency_table.shape[0], 2), dtype=float)
        superclass_index_num_samples = [0, 0]
        for value, value_num_samples in enumerate(values_num_samples):
            if value_num_samples == 0:
                continue
            for class_index in set_left_classes:
                superclass_index_num_samples[0] += contingency_table[value][class_index]
                twoing_contingency_table[value][0] += contingency_table[value][class_index]
            for class_index in set_right_classes:
                superclass_index_num_samples[1] += contingency_table[value][class_index]
                twoing_contingency_table[value][1] += contingency_table[value][class_index]
        return twoing_contingency_table, superclass_index_num_samples

    @classmethod
    def _twoing_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_twoing = float('-inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                twoing_value = cls._get_twoing_value(class_num_left,
                                                     class_num_right,
                                                     num_left_samples,
                                                     num_right_samples)
                if twoing_value > best_twoing:
                    best_twoing = twoing_value
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_twoing, best_last_left_value, best_first_right_value)

    @staticmethod
    def _get_twoing_value(class_num_left, class_num_right, num_left_samples,
                          num_right_samples):
        sum_dif = 0.0
        for left_num, right_num in zip(class_num_left, class_num_right):
            class_num_tot = left_num + right_num
            if class_num_tot == 0:
                continue
            sum_dif += abs(left_num / num_left_samples - right_num / num_right_samples)

        num_total_samples = num_left_samples + num_right_samples
        frequency_left = num_left_samples / num_total_samples
        frequency_right = num_right_samples / num_total_samples

        twoing_value = (frequency_left * frequency_right / 4.0) * sum_dif ** 2
        return twoing_value

    @staticmethod
    def _two_class_trick(original_gini, class_index_num_samples, values_seen, values_num_samples,
                         contingency_table, num_total_valid_samples):
        # TESTED!
        def _get_non_empty_class_indices(class_index_num_samples):
            # TESTED!
            first_non_empty_class = None
            second_non_empty_class = None
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples > 0:
                    if first_non_empty_class is None:
                        first_non_empty_class = class_index
                    else:
                        second_non_empty_class = class_index
                        break
            return first_non_empty_class, second_non_empty_class

        def _calculate_value_class_ratio(values_seen, values_num_samples, contingency_table,
                                         non_empty_class_indices):
            # TESTED!
            value_number_ratio = [] # [(value, number_on_second_class, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = contingency_table[curr_value][second_class_index]
                value_number_ratio.append((curr_value,
                                           number_second_non_empty,
                                           number_second_non_empty/values_num_samples[curr_value]))
            value_number_ratio.sort(key=lambda tup: tup[2])
            return value_number_ratio

        def _calculate_children_gini_index(num_left_first, num_left_second, num_right_first,
                                           num_right_second, num_left_samples, num_right_samples):
            # TESTED!
            if num_left_samples != 0:
                left_first_class_freq_ratio = float(num_left_first)/float(num_left_samples)
                left_second_class_freq_ratio = float(num_left_second)/float(num_left_samples)
                left_split_gini_index = (1.0
                                         - left_first_class_freq_ratio**2
                                         - left_second_class_freq_ratio**2)
            else:
                # We can set left_split_gini_index to any value here, since it will be multiplied
                # by zero in curr_children_gini_index
                left_split_gini_index = 1.0

            if num_right_samples != 0:
                right_first_class_freq_ratio = float(num_right_first)/float(num_right_samples)
                right_second_class_freq_ratio = float(num_right_second)/float(num_right_samples)
                right_split_gini_index = (1.0
                                          - right_first_class_freq_ratio**2
                                          - right_second_class_freq_ratio**2)
            else:
                # We can set right_split_gini_index to any value here, since it will be multiplied
                # by zero in curr_children_gini_index
                right_split_gini_index = 1.0

            curr_children_gini_index = ((num_left_samples * left_split_gini_index
                                         + num_right_samples * right_split_gini_index)
                                        / (num_left_samples + num_right_samples))
            return curr_children_gini_index

        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_class,
         second_non_empty_class) = _get_non_empty_class_indices(class_index_num_samples)
        if first_non_empty_class is None or second_non_empty_class is None:
            return (float('-inf'), {0}, set())

        value_number_ratio = _calculate_value_class_ratio(values_seen,
                                                          values_num_samples,
                                                          contingency_table,
                                                          (first_non_empty_class,
                                                           second_non_empty_class))

        best_split_total_gini_gain = float('-inf')
        best_last_left_index = 0

        num_left_first = 0
        num_left_second = 0
        num_left_samples = 0
        num_right_first = class_index_num_samples[first_non_empty_class]
        num_right_second = class_index_num_samples[second_non_empty_class]
        num_right_samples = num_total_valid_samples

        for last_left_index, (last_left_value, last_left_num_second, _) in enumerate(
                value_number_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            last_left_num_first = num_samples_last_left_value - last_left_num_second

            num_left_samples += num_samples_last_left_value
            num_left_first += last_left_num_first
            num_left_second += last_left_num_second
            num_right_samples -= num_samples_last_left_value
            num_right_first -= last_left_num_first
            num_right_second -= last_left_num_second

            curr_children_gini_index = _calculate_children_gini_index(num_left_first,
                                                                      num_left_second,
                                                                      num_right_first,
                                                                      num_right_second,
                                                                      num_left_samples,
                                                                      num_right_samples)
            curr_gini_gain = original_gini - curr_children_gini_index
            if curr_gini_gain > best_split_total_gini_gain:
                best_split_total_gini_gain = curr_gini_gain
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set([tup[0] for tup in value_number_ratio[:best_last_left_index + 1]])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_total_gini_gain, set_left_values, set_right_values)

    @staticmethod
    def _calculate_gini_index(side_num, class_num_side):
        gini_index = 1.0
        for curr_class_num_side in class_num_side:
            if curr_class_num_side > 0:
                gini_index -= (curr_class_num_side/side_num)**2
        return gini_index

    @classmethod
    def _calculate_children_gini_index(cls, left_num, class_num_left, right_num, class_num_right):
        left_split_gini_index = cls._calculate_gini_index(left_num, class_num_left)
        right_split_gini_index = cls._calculate_gini_index(right_num, class_num_right)
        children_gini_index = ((left_num * left_split_gini_index
                                + right_num * right_split_gini_index)
                               / (left_num + right_num))
        return children_gini_index



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                      GW SQUARED GINI                                      ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class GWSquaredGini(Criterion):
    """Square Gini criterion using Goemans and Williamson method for solving the Max Cut problem
    using a randomized approximation and a SDP formulation.
    """
    name = 'GW Squared Gini'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the GW Squared Gini
        criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for attrib_index, is_valid_nominal_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_nominal_attrib:
                (new_to_orig_value_int,
                 new_contingency_table,
                 new_values_num_seen) = cls._remove_empty_values(
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples)

                (curr_cut_value,
                 left_int_values,
                 right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                              new_contingency_table,
                                                              new_values_num_seen)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_int_values, right_int_values],
                          criterion_value=curr_cut_value))
        if best_splits_per_attrib:
            return max(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut).
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i in range(new_values_num_seen.shape[0]):
                for value_index_j in range(new_values_num_seen.shape[0]):
                    if value_index_i == value_index_j:
                        continue
                    for class_index in range(new_contingency_table.shape[1]):
                        num_elems_value_j_diff_class = (
                            new_values_num_seen[value_index_j]
                            - new_contingency_table[value_index_j, class_index])
                        weights[value_index_i, value_index_j] += (
                            new_contingency_table[value_index_i, class_index]
                            * num_elems_value_j_diff_class)
            return weights

        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        frac_split_cholesky = cls._solve_max_cut(weights)
        left_new_values, right_new_values = cls._generate_random_partition(frac_split_cholesky)

        left_orig_values, right_orig_values = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                            left_new_values,
                                                                            right_new_values)
        cut_val = cls._calculate_split_value(left_new_values, right_new_values, weights)
        return cut_val, left_orig_values, right_orig_values


    @staticmethod
    def _solve_max_cut(weights):
        def _solve_sdp(weights):
            # See Max Cut approximation given by Goemans and Williamson, 1995.
            var = cvx.Semidef(weights.shape[0])
            obj = cvx.Minimize(0.25 * cvx.trace(weights.T * var))

            constraints = [var == var.T, var >> 0]
            for i in range(weights.shape[0]):
                constraints.append(var[i, i] == 1)

            prob = cvx.Problem(obj, constraints)
            prob.solve(solver=cvx.SCS, verbose=False)
            return var.value

        fractional_split_squared = _solve_sdp(weights)
        # The solution should already be symmetric, but let's just make sure the approximations
        # didn't change that.
        sym_fractional_split_squared = 0.5 * (fractional_split_squared
                                              + fractional_split_squared.T)
        # We are interested in the Cholesky decomposition of the above matrix to finally choose a
        # random partition based on it. Detail: the above matrix may be singular, so not every
        # method works.
        permutation_matrix, lower_triang_matrix, _ = chol.chol_higham(sym_fractional_split_squared)

        # Note that lower_triang_matrix.T is upper triangular, but
        # frac_split_cholesky = np.dot(lower_triang_matrix.T, permutation_matrix)
        # is not necessarily upper triangular. Since we are only interested in decomposing
        # sym_fractional_split_squared = np.dot(frac_split_cholesky.T, frac_split_cholesky)
        # that is not a problem.
        return np.dot(lower_triang_matrix.T, permutation_matrix)

    @staticmethod
    def _generate_random_partition(frac_split_cholesky):
        random_vector = np.random.randn(frac_split_cholesky.shape[1])
        values_split = np.zeros((frac_split_cholesky.shape[1]), dtype=np.float64)
        for column_index in range(frac_split_cholesky.shape[1]):
            column = frac_split_cholesky[:, column_index]
            values_split[column_index] = np.dot(random_vector, column)
        values_split_bool = np.apply_along_axis(lambda x: x > 0.0, axis=0, arr=values_split)

        left_new_values = set()
        right_new_values = set()
        for new_value in range(frac_split_cholesky.shape[1]):
            if values_split_bool[new_value]:
                left_new_values.add(new_value)
            else:
                right_new_values.add(new_value)
        return left_new_values, right_new_values

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values

    @staticmethod
    def _calculate_split_value(left_new_values, right_new_values, weights):
        cut_val = 0.0
        for value_left, value_right in itertools.product(left_new_values, right_new_values):
            cut_val += weights[value_left, value_right]
        return cut_val



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                       GW CHI SQUARE                                       ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class GWChiSquare(Criterion):
    """Chi Square criterion using Goemans and Williamson method for solving the Max Cut problem
    using a randomized approximation and a SDP formulation.
    """
    name = 'GW Chi Square'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the GW Chi Square criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for attrib_index, is_valid_nominal_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_nominal_attrib:
                (new_to_orig_value_int,
                 new_contingency_table,
                 new_values_num_seen) = cls._remove_empty_values(
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples)

                (curr_cut_value,
                 left_int_values,
                 right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                              new_contingency_table,
                                                              new_values_num_seen)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_int_values, right_int_values],
                          criterion_value=curr_cut_value))
        if best_splits_per_attrib:
            return max(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # TESTED!
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut)
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i, num_samples_value_index_i in enumerate(new_values_num_seen):
                for value_index_j, num_samples_value_index_j in enumerate(new_values_num_seen):
                    if value_index_i >= value_index_j:
                        continue

                    # Let's calculate the weight of the (i,j)-th edge using the chi-square value.
                    num_samples_both_values = (num_samples_value_index_i
                                               + num_samples_value_index_j) # is always > 0.
                    for curr_class_index in range(new_contingency_table.shape[1]):
                        num_samples_both_values_curr_class = (
                            new_contingency_table[value_index_i, curr_class_index]
                            + new_contingency_table[value_index_j, curr_class_index])
                        if num_samples_both_values_curr_class == 0:
                            continue

                        expected_value_index_i_class = (
                            num_samples_value_index_i * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_i = (
                            new_contingency_table[value_index_i, curr_class_index]
                            - expected_value_index_i_class)

                        expected_value_index_j_class = (
                            num_samples_value_index_j * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_j = (
                            new_contingency_table[value_index_j, curr_class_index]
                            - expected_value_index_j_class)

                        edge_weight_curr_class = (
                            diff_index_i * (diff_index_i / expected_value_index_i_class)
                            + diff_index_j * (diff_index_j / expected_value_index_j_class))
                        weights[value_index_i, value_index_j] += edge_weight_curr_class

                    if new_values_num_seen.shape[0] > 2:
                        weights[value_index_i, value_index_j] /= (new_values_num_seen.shape[0] - 1.)
                    weights[value_index_j, value_index_i] = weights[value_index_i, value_index_j]
            return weights

        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        frac_split_cholesky = cls._solve_max_cut(weights)
        left_new_values, right_new_values = cls._generate_random_partition(frac_split_cholesky)

        left_orig_values, right_orig_values = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                            left_new_values,
                                                                            right_new_values)
        cut_val = cls._calculate_split_value(left_new_values, right_new_values, weights)
        return cut_val, left_orig_values, right_orig_values

    @staticmethod
    def _solve_max_cut(weights):
        def _solve_sdp(weights):
            # See Max Cut approximation given by Goemans and Williamson, 1995.
            var = cvx.Semidef(weights.shape[0])
            obj = cvx.Minimize(0.25 * cvx.trace(weights.T * var))

            constraints = [var == var.T, var >> 0]
            for i in range(weights.shape[0]):
                constraints.append(var[i, i] == 1)

            prob = cvx.Problem(obj, constraints)
            prob.solve(solver=cvx.SCS, verbose=False)
            return var.value

        fractional_split_squared = _solve_sdp(weights)
        # The solution should already be symmetric, but let's just make sure the approximations
        # didn't change that.
        sym_fractional_split_squared = 0.5 * (fractional_split_squared
                                              + fractional_split_squared.T)
        # We are interested in the Cholesky decomposition of the above matrix to finally choose a
        # random partition based on it. Detail: the above matrix may be singular, so not every
        # method works.
        permutation_matrix, lower_triang_matrix, _ = chol.chol_higham(sym_fractional_split_squared)

        # Note that lower_triang_matrix.T is upper triangular, but
        # frac_split_cholesky = np.dot(lower_triang_matrix.T, permutation_matrix)
        # is not necessarily upper triangular. Since we are only interested in decomposing
        # sym_fractional_split_squared = np.dot(frac_split_cholesky.T, frac_split_cholesky)
        # that is not a problem.
        return np.dot(lower_triang_matrix.T, permutation_matrix)

    @staticmethod
    def _generate_random_partition(frac_split_cholesky):
        random_vector = np.random.randn(frac_split_cholesky.shape[1])
        values_split = np.zeros((frac_split_cholesky.shape[1]), dtype=np.float64)
        for column_index in range(frac_split_cholesky.shape[1]):
            column = frac_split_cholesky[:, column_index]
            values_split[column_index] = np.dot(random_vector, column)
        values_split_bool = np.apply_along_axis(lambda x: x > 0.0, axis=0, arr=values_split)

        left_new_values = set()
        right_new_values = set()
        for new_value in range(frac_split_cholesky.shape[1]):
            if values_split_bool[new_value]:
                left_new_values.add(new_value)
            else:
                right_new_values.add(new_value)
        return left_new_values, right_new_values

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values

    @staticmethod
    def _calculate_split_value(left_new_values, right_new_values, weights):
        cut_val = 0.0
        for value_left, value_right in itertools.product(left_new_values, right_new_values):
            cut_val += weights[value_left, value_right]
        return cut_val



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                     LS Squared Gini                                       ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class LSSquaredGini(Criterion):
    """Squared Gini criterion using a greedy local search for solving the Max Cut problem.
    """
    name = 'LS Squared Gini'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the LS Squared Gini
        criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                (new_to_orig_value_int,
                 new_contingency_table,
                 new_values_num_seen) = cls._remove_empty_values(
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples)
                (curr_cut_value,
                 left_int_values,
                 right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                              new_contingency_table,
                                                              new_values_num_seen)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_int_values, right_int_values],
                          criterion_value=curr_cut_value))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (cut_val,
                 last_left_value,
                 first_right_value) = cls._best_cut_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=cut_val))
        if best_splits_per_attrib:
            return max(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut).
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i in range(new_values_num_seen.shape[0]):
                for value_index_j in range(new_values_num_seen.shape[0]):
                    if value_index_i == value_index_j:
                        continue
                    for class_index in range(new_contingency_table.shape[1]):
                        num_elems_value_j_diff_class = (
                            new_values_num_seen[value_index_j]
                            - new_contingency_table[value_index_j, class_index])
                        weights[value_index_i, value_index_j] += (
                            new_contingency_table[value_index_i, class_index]
                            * num_elems_value_j_diff_class)
            return weights


        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        # Initial partition generated through a greedy approach.
        (cut_val,
         left_new_values,
         right_new_values) = cls._generate_initial_partition(len(new_values_num_seen), weights)
        # Look for a better solution locally, changing the side of a single node or exchanging a
        # pair of nodes from different sides, while it increases the cut value.
        (cut_val_switched,
         left_new_values_switched,
         right_new_values_switched) = cls._switch_while_increase(cut_val,
                                                                 left_new_values,
                                                                 right_new_values,
                                                                 weights)
        if cut_val_switched > cut_val:
            cut_val = cut_val_switched
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values_switched,
                                                                right_new_values_switched)
        else:
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values,
                                                                right_new_values)
        return cut_val, left_orig_values, right_orig_values

    @classmethod
    def _generate_initial_partition(cls, num_values, weights):
        set_left_values = set()
        set_right_values = set()
        cut_val = 0.0

        for value in range(num_values):
            if not set_left_values: # first node goes to the left
                set_left_values.add(value)
                continue
            gain_assigning_right = sum(weights[value][left_value]
                                       for left_value in set_left_values)
            gain_assigning_left = sum(weights[value][right_value]
                                      for right_value in set_right_values)
            if gain_assigning_right >= gain_assigning_left:
                set_right_values.add(value)
                cut_val += gain_assigning_right
            else:
                set_left_values.add(value)
                cut_val += gain_assigning_left
        return cut_val, set_left_values, set_right_values

    @classmethod
    def _switch_while_increase(cls, cut_val, set_left_values, set_right_values, weights):
        curr_cut_val = cut_val
        values_seen = set_left_values | set_right_values

        found_improvement = True
        while found_improvement:
            found_improvement = False

            # Try to switch the side of a single node (`value`) to improve the cut value.
            for value in values_seen:
                new_cut_val = cls._split_gain_for_single_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                value,
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value in set_left_values:
                        set_left_values.remove(value)
                        set_right_values.add(value)
                    else:
                        set_left_values.add(value)
                        set_right_values.remove(value)
                    found_improvement = True
                    break
            if found_improvement:
                continue

            # Try to switch a pair of nodes (`value1` and `value2`) from different sides to improve
            # the cut value.
            for value1, value2 in itertools.combinations(values_seen, 2):
                if ((value1 in set_left_values and value2 in set_left_values) or
                        (value1 in set_right_values and value2 in set_right_values)):
                    continue
                new_cut_val = cls._split_gain_for_double_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                (value1, value2),
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value1 in set_left_values:
                        set_left_values.remove(value1)
                        set_right_values.add(value1)
                        set_right_values.remove(value2)
                        set_left_values.add(value2)
                    else:
                        set_left_values.remove(value2)
                        set_right_values.add(value2)
                        set_right_values.remove(value1)
                        set_left_values.add(value1)
                    found_improvement = True
                    break
        return curr_cut_val, set_left_values, set_right_values

    @staticmethod
    def _split_gain_for_single_switch(curr_gain, left_new_values, right_new_values,
                                      new_value_to_change_sides, weights):
        new_gain = curr_gain
        if new_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
            for value in right_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
        else:
            for value in left_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
            for value in right_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
        return new_gain

    @staticmethod
    def _split_gain_for_double_switch(curr_gain, left_new_values, right_new_values,
                                      new_values_to_change_sides, weights):
        assert len(new_values_to_change_sides) == 2
        new_gain = curr_gain
        first_value_to_change_sides = new_values_to_change_sides[0]
        second_value_to_change_sides = new_values_to_change_sides[1]

        if first_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
        else:
            for value in left_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
        return new_gain

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _best_cut_for_numeric(cls, sorted_values_and_classes, num_classes):
        # Initial state is having the first value of `sorted_values_and_classes` on the left and
        # everything else on the right.
        last_left_new_value = sorted_values_and_classes[0][0]
        last_left_class = sorted_values_and_classes[0][1]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[last_left_class] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        # Note that this cut with only the first sample on the left might not be valid: the value on
        # the left might also appears on the right of the split. Therefore we initialize with cut
        # value = -inf and only check if the current split is valid (and maybe update the
        # information about the best cut found) on the next loop iteration. Note that, by doing
        # this, we never test the split where the last sample is in the left, because there would be
        # no samples on the right.
        best_cut_value = float('-inf')
        best_last_left_new_value = None
        best_first_right_new_value = None

        # `curr_cut_value` holds the current cut value, even if it's not a valid cut.
        curr_cut_value = num_right_samples - class_num_right[last_left_class]

        for (first_right_new_value, first_right_class) in sorted_values_and_classes[1:]:
            if first_right_new_value != last_left_new_value and curr_cut_value > best_cut_value:
                best_cut_value = curr_cut_value
                best_last_left_new_value = last_left_new_value
                best_first_right_new_value = first_right_new_value

            curr_cut_value -= num_left_samples - class_num_left[first_right_class]
            num_left_samples += 1
            num_right_samples -= 1
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
            curr_cut_value += num_right_samples - class_num_right[first_right_class]
            last_left_new_value = first_right_new_value

        return (best_cut_value, best_last_left_new_value, best_first_right_new_value)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                       LS Chi Square                                       ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class LSChiSquare(Criterion):
    """Chi Square criterion using a greedy local search for solving the Max Cut problem.
    """
    name = 'LS Chi Square'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the LS Chi Square criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                (new_to_orig_value_int,
                 new_contingency_table,
                 new_values_num_seen) = cls._remove_empty_values(
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples)
                (curr_cut_value,
                 left_int_values,
                 right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                              new_contingency_table,
                                                              new_values_num_seen)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_int_values, right_int_values],
                          criterion_value=curr_cut_value))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (cut_val,
                 last_left_value,
                 first_right_value) = cls._best_cut_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes,
                     tree_node.class_index_num_samples)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=cut_val))
        if best_splits_per_attrib:
            return max(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut)
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i, num_samples_value_index_i in enumerate(new_values_num_seen):
                for value_index_j, num_samples_value_index_j in enumerate(new_values_num_seen):
                    if value_index_i >= value_index_j:
                        continue
                    num_samples_both_values = (num_samples_value_index_i
                                               + num_samples_value_index_j) # is always > 0.
                    for curr_class_index in range(new_contingency_table.shape[1]):
                        num_samples_both_values_curr_class = (
                            new_contingency_table[value_index_i, curr_class_index]
                            + new_contingency_table[value_index_j, curr_class_index])
                        if num_samples_both_values_curr_class == 0:
                            continue

                        expected_value_index_i_class = (
                            num_samples_value_index_i * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_i = (
                            new_contingency_table[value_index_i, curr_class_index]
                            - expected_value_index_i_class)

                        expected_value_index_j_class = (
                            num_samples_value_index_j * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_j = (
                            new_contingency_table[value_index_j, curr_class_index]
                            - expected_value_index_j_class)

                        edge_weight_curr_class = (
                            diff_index_i * (diff_index_i / expected_value_index_i_class)
                            + diff_index_j * (diff_index_j / expected_value_index_j_class))
                        weights[value_index_i, value_index_j] += edge_weight_curr_class

                    if new_values_num_seen.shape[0] > 2:
                        weights[value_index_i, value_index_j] /= (new_values_num_seen.shape[0] - 1.)
                    weights[value_index_j, value_index_i] = weights[value_index_i, value_index_j]
            return weights


        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        # Initial partition generated through a greedy approach.
        (cut_val,
         left_new_values,
         right_new_values) = cls._generate_initial_partition(len(new_values_num_seen), weights)
        # Look for a better solution locally, changing the side of a single node or exchanging a
        # pair of nodes from different sides, while it increases the cut value.
        (cut_val_switched,
         left_new_values_switched,
         right_new_values_switched) = cls._switch_while_increase(cut_val,
                                                                 left_new_values,
                                                                 right_new_values,
                                                                 weights)
        if cut_val_switched > cut_val:
            cut_val = cut_val_switched
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values_switched,
                                                                right_new_values_switched)
        else:
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values,
                                                                right_new_values)
        return cut_val, left_orig_values, right_orig_values

    @classmethod
    def _generate_initial_partition(cls, num_values, weights):
        set_left_values = set()
        set_right_values = set()
        cut_val = 0.0

        for value in range(num_values):
            if not set_left_values: # first node goes to the left
                set_left_values.add(value)
                continue
            gain_assigning_right = sum(weights[value][left_value]
                                       for left_value in set_left_values)
            gain_assigning_left = sum(weights[value][right_value]
                                      for right_value in set_right_values)
            if gain_assigning_right >= gain_assigning_left:
                set_right_values.add(value)
                cut_val += gain_assigning_right
            else:
                set_left_values.add(value)
                cut_val += gain_assigning_left
        return cut_val, set_left_values, set_right_values

    @classmethod
    def _switch_while_increase(cls, cut_val, set_left_values, set_right_values, weights):
        curr_cut_val = cut_val
        values_seen = set_left_values | set_right_values

        found_improvement = True
        while found_improvement:
            found_improvement = False

            # Try to switch the side of a single node (`value`) to improve the cut value.
            for value in values_seen:
                new_cut_val = cls._split_gain_for_single_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                value,
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value in set_left_values:
                        set_left_values.remove(value)
                        set_right_values.add(value)
                    else:
                        set_left_values.add(value)
                        set_right_values.remove(value)
                    found_improvement = True
                    break
            if found_improvement:
                continue

            # Try to switch a pair of nodes (`value1` and `value2`) from different sides to improve
            # the cut value.
            for value1, value2 in itertools.combinations(values_seen, 2):
                if ((value1 in set_left_values and value2 in set_left_values) or
                        (value1 in set_right_values and value2 in set_right_values)):
                    continue
                new_cut_val = cls._split_gain_for_double_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                (value1, value2),
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value1 in set_left_values:
                        set_left_values.remove(value1)
                        set_right_values.add(value1)
                        set_right_values.remove(value2)
                        set_left_values.add(value2)
                    else:
                        set_left_values.remove(value2)
                        set_right_values.add(value2)
                        set_right_values.remove(value1)
                        set_left_values.add(value1)
                    found_improvement = True
                    break
        return curr_cut_val, set_left_values, set_right_values

    @staticmethod
    def _split_gain_for_single_switch(curr_gain, left_new_values, right_new_values,
                                      new_value_to_change_sides, weights):
        new_gain = curr_gain
        if new_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
            for value in right_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
        else:
            for value in left_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
            for value in right_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
        return new_gain

    @staticmethod
    def _split_gain_for_double_switch(curr_gain, left_new_values, right_new_values,
                                      new_values_to_change_sides, weights):
        assert len(new_values_to_change_sides) == 2
        new_gain = curr_gain
        first_value_to_change_sides = new_values_to_change_sides[0]
        second_value_to_change_sides = new_values_to_change_sides[1]

        if first_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
        else:
            for value in left_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
        return new_gain

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _best_cut_for_numeric(cls, sorted_values_and_classes, num_classes, class_index_num_samples):
        # Initial state is having the first value of `sorted_values_and_classes` on the left and
        # everything else on the right.
        last_left_new_value = sorted_values_and_classes[0][0]
        last_left_class = sorted_values_and_classes[0][1]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1
        num_samples = len(sorted_values_and_classes)

        class_num_left = [0] * num_classes
        class_num_left[last_left_class] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        # Note that this cut with only the first sample on the left might not be valid: the value on
        # the left might also appears on the right of the split. Therefore we initialize with cut
        # value = -inf and only check if the current split is valid (and maybe update the
        # information about the best cut found) on the next loop iteration. Note that, by doing
        # this, we never test the split where the last sample is in the left, because there would be
        # no samples on the right.
        best_cut_value = float('-inf')
        best_last_left_new_value = None
        best_first_right_new_value = None

        for (first_right_new_value, first_right_class) in sorted_values_and_classes[1:]:
            # `curr_cut_value` holds the current cut value, even if it's not a valid cut.
            curr_cut_value = 0.0
            for class_index in range(num_classes):
                if class_index_num_samples[class_index] != 0:
                    expected_value_left_class = (
                        num_left_samples * class_index_num_samples[class_index] / num_samples)
                    diff_left = class_num_left[class_index] - expected_value_left_class
                    curr_cut_value += diff_left * (diff_left / expected_value_left_class)

                    expected_value_right_class = (
                        num_right_samples * class_index_num_samples[class_index] / num_samples)
                    diff_right = class_num_right[class_index] - expected_value_right_class
                    curr_cut_value += diff_right * (diff_right / expected_value_right_class)

            if first_right_new_value != last_left_new_value and curr_cut_value > best_cut_value:
                best_cut_value = curr_cut_value
                best_last_left_new_value = last_left_new_value
                best_first_right_new_value = first_right_new_value
                last_left_new_value = first_right_new_value

            num_left_samples += 1
            num_right_samples -= 1
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1

        return (best_cut_value, best_last_left_new_value, best_first_right_new_value)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                            CONDITIONAL INFERENCE TREE TWOING                              ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeTwoing(Criterion):
    """
    Conditional Inference Tree using Twoing criterion to find best split. For references, see
    "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik & A.
    Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006" and
    "Breiman, L., Friedman, J. J., Olshen, R. A., and Stone, C. J. Classification and Regression
    Trees. Wadsworth, 1984".
    """
    name = 'Conditional Inference Tree Twoing'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the Twoing criterion to find the best split
        for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            # Let's find the best split for this attribute using the Twoing criterion.
            best_total_gini_gain = float('-inf')
            best_left_values = set()
            best_right_values = set()
            values_seen = cls._get_values_seen(
                tree_node.contingency_tables[best_split.attrib_index].values_num_samples)
            for (set_left_classes,
                 set_right_classes) in cls._generate_twoing(tree_node.class_index_num_samples):
                (twoing_contingency_table,
                 superclass_index_num_samples) = cls._get_twoing_contingency_table(
                     tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                     tree_node.contingency_tables[best_split.attrib_index].values_num_samples,
                     set_left_classes,
                     set_right_classes)
                original_gini = cls._calculate_gini_index(len(tree_node.valid_samples_indices),
                                                          superclass_index_num_samples)
                (curr_gini_gain,
                 left_values,
                 right_values) = cls._two_class_trick(
                     original_gini,
                     superclass_index_num_samples,
                     values_seen,
                     tree_node.contingency_tables[best_split.attrib_index].values_num_samples,
                     twoing_contingency_table,
                     len(tree_node.valid_samples_indices))
                if curr_gini_gain > best_total_gini_gain:
                    best_total_gini_gain = curr_gini_gain
                    best_left_values = left_values
                    best_right_values = right_values
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[best_left_values, best_right_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _generate_twoing(class_index_num_samples):
        # We only need to look at superclasses of up to (len(class_index_num_samples)/2 + 1)
        # elements because of symmetry! The subsets we are not choosing are complements of the ones
        # chosen.
        non_empty_classes = set([])
        for class_index, class_num_samples in enumerate(class_index_num_samples):
            if class_num_samples > 0:
                non_empty_classes.add(class_index)
        number_non_empty_classes = len(non_empty_classes)

        for left_classes in itertools.chain.from_iterable(
                itertools.combinations(non_empty_classes, size_left_superclass)
                for size_left_superclass in range(1, number_non_empty_classes // 2 + 1)):
            set_left_classes = set(left_classes)
            set_right_classes = non_empty_classes - set_left_classes
            if not set_left_classes or not set_right_classes:
                # A valid split must have at least one sample in each side
                continue
            yield set_left_classes, set_right_classes

    @staticmethod
    def _get_twoing_contingency_table(contingency_table, values_num_samples, set_left_classes,
                                      set_right_classes):
        twoing_contingency_table = np.zeros((contingency_table.shape[0], 2), dtype=float)
        superclass_index_num_samples = [0, 0]
        for value, value_num_samples in enumerate(values_num_samples):
            if value_num_samples == 0:
                continue
            for class_index in set_left_classes:
                superclass_index_num_samples[0] += contingency_table[value][class_index]
                twoing_contingency_table[value][0] += contingency_table[value][class_index]
            for class_index in set_right_classes:
                superclass_index_num_samples[1] += contingency_table[value][class_index]
                twoing_contingency_table[value][1] += contingency_table[value][class_index]
        return twoing_contingency_table, superclass_index_num_samples

    @staticmethod
    def _two_class_trick(original_gini, class_index_num_samples, values_seen, values_num_samples,
                         contingency_table, num_total_valid_samples):
        # TESTED!
        def _get_non_empty_class_indices(class_index_num_samples):
            # TESTED!
            first_non_empty_class = None
            second_non_empty_class = None
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples > 0:
                    if first_non_empty_class is None:
                        first_non_empty_class = class_index
                    else:
                        second_non_empty_class = class_index
                        break
            return first_non_empty_class, second_non_empty_class

        def _calculate_value_class_ratio(values_seen, values_num_samples, contingency_table,
                                         non_empty_class_indices):
            # TESTED!
            value_number_ratio = [] # [(value, number_on_second_class, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = contingency_table[curr_value][second_class_index]
                value_number_ratio.append((curr_value,
                                           number_second_non_empty,
                                           number_second_non_empty/values_num_samples[curr_value]))
            value_number_ratio.sort(key=lambda tup: tup[2])
            return value_number_ratio

        def _calculate_children_gini_index(num_left_first, num_left_second, num_right_first,
                                           num_right_second, num_left_samples, num_right_samples):
            # TESTED!
            if num_left_samples != 0:
                left_first_class_freq_ratio = float(num_left_first)/float(num_left_samples)
                left_second_class_freq_ratio = float(num_left_second)/float(num_left_samples)
                left_split_gini_index = (1.0
                                         - left_first_class_freq_ratio**2
                                         - left_second_class_freq_ratio**2)
            else:
                # We can set left_split_gini_index to any value here, since it will be multiplied
                # by zero in curr_children_gini_index
                left_split_gini_index = 1.0

            if num_right_samples != 0:
                right_first_class_freq_ratio = float(num_right_first)/float(num_right_samples)
                right_second_class_freq_ratio = float(num_right_second)/float(num_right_samples)
                right_split_gini_index = (1.0
                                          - right_first_class_freq_ratio**2
                                          - right_second_class_freq_ratio**2)
            else:
                # We can set right_split_gini_index to any value here, since it will be multiplied
                # by zero in curr_children_gini_index
                right_split_gini_index = 1.0

            curr_children_gini_index = ((num_left_samples * left_split_gini_index
                                         + num_right_samples * right_split_gini_index)
                                        / (num_left_samples + num_right_samples))
            return curr_children_gini_index

        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_class,
         second_non_empty_class) = _get_non_empty_class_indices(class_index_num_samples)
        if first_non_empty_class is None or second_non_empty_class is None:
            return (float('-inf'), {0}, set())

        value_number_ratio = _calculate_value_class_ratio(values_seen,
                                                          values_num_samples,
                                                          contingency_table,
                                                          (first_non_empty_class,
                                                           second_non_empty_class))

        best_split_total_gini_gain = float('-inf')
        best_last_left_index = 0

        num_left_first = 0
        num_left_second = 0
        num_left_samples = 0
        num_right_first = class_index_num_samples[first_non_empty_class]
        num_right_second = class_index_num_samples[second_non_empty_class]
        num_right_samples = num_total_valid_samples

        for last_left_index, (last_left_value, last_left_num_second, _) in enumerate(
                value_number_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            last_left_num_first = num_samples_last_left_value - last_left_num_second

            num_left_samples += num_samples_last_left_value
            num_left_first += last_left_num_first
            num_left_second += last_left_num_second
            num_right_samples -= num_samples_last_left_value
            num_right_first -= last_left_num_first
            num_right_second -= last_left_num_second

            curr_children_gini_index = _calculate_children_gini_index(num_left_first,
                                                                      num_left_second,
                                                                      num_right_first,
                                                                      num_right_second,
                                                                      num_left_samples,
                                                                      num_right_samples)
            curr_gini_gain = original_gini - curr_children_gini_index
            if curr_gini_gain > best_split_total_gini_gain:
                best_split_total_gini_gain = curr_gini_gain
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set([tup[0] for tup in value_number_ratio[:best_last_left_index + 1]])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_total_gini_gain, set_left_values, set_right_values)

    @staticmethod
    def _calculate_gini_index(side_num, class_num_side):
        gini_index = 1.0
        for curr_class_num_side in class_num_side:
            if curr_class_num_side > 0:
                gini_index -= (curr_class_num_side/side_num)**2
        return gini_index

    @classmethod
    def _calculate_children_gini_index(cls, left_num, class_num_left, right_num, class_num_right):
        left_split_gini_index = cls._calculate_gini_index(left_num, class_num_left)
        right_split_gini_index = cls._calculate_gini_index(right_num, class_num_right)
        children_gini_index = ((left_num * left_split_gini_index
                                + right_num * right_split_gini_index)
                               / (left_num + right_num))
        return children_gini_index



#################################################################################################
#################################################################################################
###                                                                                           ###
###                        CONDITIONAL INFERENCE TREE LS SQUARED GINI                         ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeLSSquaredGini(Criterion):
    """
    Conditional Inference Tree using LS Squared Gini criterion to find best split. For reference,
    see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik
    & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006".
    """
    name = 'Conditional Inference Tree LS Squared Gini'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the LS Squared Gini criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            # Let's find the best split for this attribute using the LS Squared Gini criterion.
            (new_to_orig_value_int,
             new_contingency_table,
             new_values_num_seen) = cls._remove_empty_values(
                 tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                 tree_node.contingency_tables[best_split.attrib_index].values_num_samples)
            (_,
             left_int_values,
             right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                          new_contingency_table,
                                                          new_values_num_seen)
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[left_int_values, right_int_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut).
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i in range(new_values_num_seen.shape[0]):
                for value_index_j in range(new_values_num_seen.shape[0]):
                    if value_index_i == value_index_j:
                        continue
                    for class_index in range(new_contingency_table.shape[1]):
                        num_elems_value_j_diff_class = (
                            new_values_num_seen[value_index_j]
                            - new_contingency_table[value_index_j, class_index])
                        weights[value_index_i, value_index_j] += (
                            new_contingency_table[value_index_i, class_index]
                            * num_elems_value_j_diff_class)
            return weights


        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        # Initial partition generated through a greedy approach.
        (cut_val,
         left_new_values,
         right_new_values) = cls._generate_initial_partition(len(new_values_num_seen), weights)
        # Look for a better solution locally, changing the side of a single node or exchanging a
        # pair of nodes from different sides, while it increases the cut value.
        (cut_val_switched,
         left_new_values_switched,
         right_new_values_switched) = cls._switch_while_increase(cut_val,
                                                                 left_new_values,
                                                                 right_new_values,
                                                                 weights)
        if cut_val_switched > cut_val:
            cut_val = cut_val_switched
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values_switched,
                                                                right_new_values_switched)
        else:
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values,
                                                                right_new_values)
        return cut_val, left_orig_values, right_orig_values

    @classmethod
    def _generate_initial_partition(cls, num_values, weights):
        set_left_values = set()
        set_right_values = set()
        cut_val = 0.0

        for value in range(num_values):
            if not set_left_values: # first node goes to the left
                set_left_values.add(value)
                continue
            gain_assigning_right = sum(weights[value][left_value]
                                       for left_value in set_left_values)
            gain_assigning_left = sum(weights[value][right_value]
                                      for right_value in set_right_values)
            if gain_assigning_right >= gain_assigning_left:
                set_right_values.add(value)
                cut_val += gain_assigning_right
            else:
                set_left_values.add(value)
                cut_val += gain_assigning_left
        return cut_val, set_left_values, set_right_values

    @classmethod
    def _switch_while_increase(cls, cut_val, set_left_values, set_right_values, weights):
        curr_cut_val = cut_val
        values_seen = set_left_values | set_right_values

        found_improvement = True
        while found_improvement:
            found_improvement = False

            # Try to switch the side of a single node (`value`) to improve the cut value.
            for value in values_seen:
                new_cut_val = cls._split_gain_for_single_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                value,
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value in set_left_values:
                        set_left_values.remove(value)
                        set_right_values.add(value)
                    else:
                        set_left_values.add(value)
                        set_right_values.remove(value)
                    found_improvement = True
                    break
            if found_improvement:
                continue

            # Try to switch a pair of nodes (`value1` and `value2`) from different sides to improve
            # the cut value.
            for value1, value2 in itertools.combinations(values_seen, 2):
                if ((value1 in set_left_values and value2 in set_left_values) or
                        (value1 in set_right_values and value2 in set_right_values)):
                    continue
                new_cut_val = cls._split_gain_for_double_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                (value1, value2),
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value1 in set_left_values:
                        set_left_values.remove(value1)
                        set_right_values.add(value1)
                        set_right_values.remove(value2)
                        set_left_values.add(value2)
                    else:
                        set_left_values.remove(value2)
                        set_right_values.add(value2)
                        set_right_values.remove(value1)
                        set_left_values.add(value1)
                    found_improvement = True
                    break
        return curr_cut_val, set_left_values, set_right_values

    @staticmethod
    def _split_gain_for_single_switch(curr_gain, left_new_values, right_new_values,
                                      new_value_to_change_sides, weights):
        new_gain = curr_gain
        if new_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
            for value in right_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
        else:
            for value in left_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
            for value in right_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
        return new_gain

    @staticmethod
    def _split_gain_for_double_switch(curr_gain, left_new_values, right_new_values,
                                      new_values_to_change_sides, weights):
        assert len(new_values_to_change_sides) == 2
        new_gain = curr_gain
        first_value_to_change_sides = new_values_to_change_sides[0]
        second_value_to_change_sides = new_values_to_change_sides[1]

        if first_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
        else:
            for value in left_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
        return new_gain

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values



#################################################################################################
#################################################################################################
###                                                                                           ###
###                          CONDITIONAL INFERENCE TREE LS CHI SQUARE                         ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeLSChiSquare(Criterion):
    """
    Conditional Inference Tree using LS Chi Square criterion to find best split. For reference,
    see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik
    & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006".
    """
    name = 'Conditional Inference Tree LS Chi Square'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the LS CHi Square criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            # Let's find the best split for this attribute using the LS Chi Square criterion.
            (new_to_orig_value_int,
             new_contingency_table,
             new_values_num_seen) = cls._remove_empty_values(
                 tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                 tree_node.contingency_tables[best_split.attrib_index].values_num_samples)
            (_,
             left_int_values,
             right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                          new_contingency_table,
                                                          new_values_num_seen)
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[left_int_values, right_int_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut)
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i, num_samples_value_index_i in enumerate(new_values_num_seen):
                for value_index_j, num_samples_value_index_j in enumerate(new_values_num_seen):
                    if value_index_i >= value_index_j:
                        continue
                    num_samples_both_values = (num_samples_value_index_i
                                               + num_samples_value_index_j) # is always > 0.
                    for curr_class_index in range(new_contingency_table.shape[1]):
                        num_samples_both_values_curr_class = (
                            new_contingency_table[value_index_i, curr_class_index]
                            + new_contingency_table[value_index_j, curr_class_index])
                        if num_samples_both_values_curr_class == 0:
                            continue

                        expected_value_index_i_class = (
                            num_samples_value_index_i * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_i = (
                            new_contingency_table[value_index_i, curr_class_index]
                            - expected_value_index_i_class)

                        expected_value_index_j_class = (
                            num_samples_value_index_j * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_j = (
                            new_contingency_table[value_index_j, curr_class_index]
                            - expected_value_index_j_class)

                        edge_weight_curr_class = (
                            diff_index_i * (diff_index_i / expected_value_index_i_class)
                            + diff_index_j * (diff_index_j / expected_value_index_j_class))
                        weights[value_index_i, value_index_j] += edge_weight_curr_class

                    if new_values_num_seen.shape[0] > 2:
                        weights[value_index_i, value_index_j] /= (new_values_num_seen.shape[0] - 1.)
                    weights[value_index_j, value_index_i] = weights[value_index_i, value_index_j]
            return weights


        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        # Initial partition generated through a greedy approach.
        (cut_val,
         left_new_values,
         right_new_values) = cls._generate_initial_partition(len(new_values_num_seen), weights)
        # Look for a better solution locally, changing the side of a single node or exchanging a
        # pair of nodes from different sides, while it increases the cut value.
        (cut_val_switched,
         left_new_values_switched,
         right_new_values_switched) = cls._switch_while_increase(cut_val,
                                                                 left_new_values,
                                                                 right_new_values,
                                                                 weights)
        if cut_val_switched > cut_val:
            cut_val = cut_val_switched
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values_switched,
                                                                right_new_values_switched)
        else:
            (left_orig_values,
             right_orig_values) = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                left_new_values,
                                                                right_new_values)
        return cut_val, left_orig_values, right_orig_values

    @classmethod
    def _generate_initial_partition(cls, num_values, weights):
        set_left_values = set()
        set_right_values = set()
        cut_val = 0.0

        for value in range(num_values):
            if not set_left_values: # first node goes to the left
                set_left_values.add(value)
                continue
            gain_assigning_right = sum(weights[value][left_value]
                                       for left_value in set_left_values)
            gain_assigning_left = sum(weights[value][right_value]
                                      for right_value in set_right_values)
            if gain_assigning_right >= gain_assigning_left:
                set_right_values.add(value)
                cut_val += gain_assigning_right
            else:
                set_left_values.add(value)
                cut_val += gain_assigning_left
        return cut_val, set_left_values, set_right_values

    @classmethod
    def _switch_while_increase(cls, cut_val, set_left_values, set_right_values, weights):
        curr_cut_val = cut_val
        values_seen = set_left_values | set_right_values

        found_improvement = True
        while found_improvement:
            found_improvement = False

            # Try to switch the side of a single node (`value`) to improve the cut value.
            for value in values_seen:
                new_cut_val = cls._split_gain_for_single_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                value,
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value in set_left_values:
                        set_left_values.remove(value)
                        set_right_values.add(value)
                    else:
                        set_left_values.add(value)
                        set_right_values.remove(value)
                    found_improvement = True
                    break
            if found_improvement:
                continue

            # Try to switch a pair of nodes (`value1` and `value2`) from different sides to improve
            # the cut value.
            for value1, value2 in itertools.combinations(values_seen, 2):
                if ((value1 in set_left_values and value2 in set_left_values) or
                        (value1 in set_right_values and value2 in set_right_values)):
                    continue
                new_cut_val = cls._split_gain_for_double_switch(curr_cut_val,
                                                                set_left_values,
                                                                set_right_values,
                                                                (value1, value2),
                                                                weights)
                if new_cut_val - curr_cut_val >= EPSILON:
                    curr_cut_val = new_cut_val
                    if value1 in set_left_values:
                        set_left_values.remove(value1)
                        set_right_values.add(value1)
                        set_right_values.remove(value2)
                        set_left_values.add(value2)
                    else:
                        set_left_values.remove(value2)
                        set_right_values.add(value2)
                        set_right_values.remove(value1)
                        set_left_values.add(value1)
                    found_improvement = True
                    break
        return curr_cut_val, set_left_values, set_right_values

    @staticmethod
    def _split_gain_for_single_switch(curr_gain, left_new_values, right_new_values,
                                      new_value_to_change_sides, weights):
        new_gain = curr_gain
        if new_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
            for value in right_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
        else:
            for value in left_new_values:
                new_gain -= weights[value][new_value_to_change_sides]
            for value in right_new_values:
                if value == new_value_to_change_sides:
                    continue
                new_gain += weights[value][new_value_to_change_sides]
        return new_gain

    @staticmethod
    def _split_gain_for_double_switch(curr_gain, left_new_values, right_new_values,
                                      new_values_to_change_sides, weights):
        assert len(new_values_to_change_sides) == 2
        new_gain = curr_gain
        first_value_to_change_sides = new_values_to_change_sides[0]
        second_value_to_change_sides = new_values_to_change_sides[1]

        if first_value_to_change_sides in left_new_values:
            for value in left_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
        else:
            for value in left_new_values:
                if value == second_value_to_change_sides:
                    continue
                new_gain -= weights[value][first_value_to_change_sides]
                new_gain += weights[value][second_value_to_change_sides]
            for value in right_new_values:
                if value == first_value_to_change_sides:
                    continue
                new_gain += weights[value][first_value_to_change_sides]
                new_gain -= weights[value][second_value_to_change_sides]
        return new_gain

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values



#################################################################################################
#################################################################################################
###                                                                                           ###
###                        CONDITIONAL INFERENCE TREE GW SQUARED GINI                         ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeGWSquaredGini(Criterion):
    """
    Conditional Inference Tree using GW Squared Gini criterion to find best split. For reference,
    see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik
    & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006".
    """
    name = 'Conditional Inference Tree GW Squared Gini'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the GW Squared Gini criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            # Let's find the best split for this attribute using the GW Squared Gini criterion.
            (new_to_orig_value_int,
             new_contingency_table,
             new_values_num_seen) = cls._remove_empty_values(
                 tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                 tree_node.contingency_tables[best_split.attrib_index].values_num_samples)

            (left_int_values,
             right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                          new_contingency_table,
                                                          new_values_num_seen)
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[left_int_values, right_int_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut).
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i in range(new_values_num_seen.shape[0]):
                for value_index_j in range(new_values_num_seen.shape[0]):
                    if value_index_i == value_index_j:
                        continue
                    for class_index in range(new_contingency_table.shape[1]):
                        num_elems_value_j_diff_class = (
                            new_values_num_seen[value_index_j]
                            - new_contingency_table[value_index_j, class_index])
                        weights[value_index_i, value_index_j] += (
                            new_contingency_table[value_index_i, class_index]
                            * num_elems_value_j_diff_class)
            return weights

        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        frac_split_cholesky = cls._solve_max_cut(weights)
        left_new_values, right_new_values = cls._generate_random_partition(frac_split_cholesky)

        left_orig_values, right_orig_values = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                            left_new_values,
                                                                            right_new_values)
        return left_orig_values, right_orig_values


    @staticmethod
    def _solve_max_cut(weights):
        def _solve_sdp(weights):
            # See Max Cut approximation given by Goemans and Williamson, 1995.
            var = cvx.Semidef(weights.shape[0])
            obj = cvx.Minimize(0.25 * cvx.trace(weights.T * var))

            constraints = [var == var.T, var >> 0]
            for i in range(weights.shape[0]):
                constraints.append(var[i, i] == 1)

            prob = cvx.Problem(obj, constraints)
            prob.solve(solver=cvx.SCS, verbose=False)
            return var.value

        fractional_split_squared = _solve_sdp(weights)
        # The solution should already be symmetric, but let's just make sure the approximations
        # didn't change that.
        sym_fractional_split_squared = 0.5 * (fractional_split_squared
                                              + fractional_split_squared.T)
        # We are interested in the Cholesky decomposition of the above matrix to finally choose a
        # random partition based on it. Detail: the above matrix may be singular, so not every
        # method works.
        permutation_matrix, lower_triang_matrix, _ = chol.chol_higham(sym_fractional_split_squared)

        # Note that lower_triang_matrix.T is upper triangular, but
        # frac_split_cholesky = np.dot(lower_triang_matrix.T, permutation_matrix)
        # is not necessarily upper triangular. Since we are only interested in decomposing
        # sym_fractional_split_squared = np.dot(frac_split_cholesky.T, frac_split_cholesky)
        # that is not a problem.
        return np.dot(lower_triang_matrix.T, permutation_matrix)

    @staticmethod
    def _generate_random_partition(frac_split_cholesky):
        random_vector = np.random.randn(frac_split_cholesky.shape[1])
        values_split = np.zeros((frac_split_cholesky.shape[1]), dtype=np.float64)
        for column_index in range(frac_split_cholesky.shape[1]):
            column = frac_split_cholesky[:, column_index]
            values_split[column_index] = np.dot(random_vector, column)
        values_split_bool = np.apply_along_axis(lambda x: x > 0.0, axis=0, arr=values_split)

        left_new_values = set()
        right_new_values = set()
        for new_value in range(frac_split_cholesky.shape[1]):
            if values_split_bool[new_value]:
                left_new_values.add(new_value)
            else:
                right_new_values.add(new_value)
        return left_new_values, right_new_values

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values



#################################################################################################
#################################################################################################
###                                                                                           ###
###                          CONDITIONAL INFERENCE TREE GW CHI SQUARE                         ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeGWChiSquare(Criterion):
    """
    Conditional Inference Tree using GW Chi Square criterion to find best split. For reference,
    see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik
    & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006".
    """
    name = 'Conditional Inference Tree GW Chi Square'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the GW CHi Square criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            # Let's find the best split for this attribute using the GW Chi Square criterion.
            (new_to_orig_value_int,
             new_contingency_table,
             new_values_num_seen) = cls._remove_empty_values(
                 tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                 tree_node.contingency_tables[best_split.attrib_index].values_num_samples)

            (left_int_values,
             right_int_values) = cls._generate_best_split(new_to_orig_value_int,
                                                          new_contingency_table,
                                                          new_values_num_seen)
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[left_int_values, right_int_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _generate_best_split(cls, new_to_orig_value_int, new_contingency_table,
                             new_values_num_seen):
        def _init_values_weights(new_contingency_table, new_values_num_seen):
            # TESTED!
            # Initializes the weight of each edge in the values graph (to be sent to the Max Cut)
            weights = np.zeros((new_values_num_seen.shape[0], new_values_num_seen.shape[0]),
                               dtype=np.float64)
            for value_index_i, num_samples_value_index_i in enumerate(new_values_num_seen):
                for value_index_j, num_samples_value_index_j in enumerate(new_values_num_seen):
                    if value_index_i >= value_index_j:
                        continue

                    # Let's calculate the weight of the (i,j)-th edge using the chi-square value.
                    num_samples_both_values = (num_samples_value_index_i
                                               + num_samples_value_index_j) # is always > 0.
                    for curr_class_index in range(new_contingency_table.shape[1]):
                        num_samples_both_values_curr_class = (
                            new_contingency_table[value_index_i, curr_class_index]
                            + new_contingency_table[value_index_j, curr_class_index])
                        if num_samples_both_values_curr_class == 0:
                            continue

                        expected_value_index_i_class = (
                            num_samples_value_index_i * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_i = (
                            new_contingency_table[value_index_i, curr_class_index]
                            - expected_value_index_i_class)

                        expected_value_index_j_class = (
                            num_samples_value_index_j * num_samples_both_values_curr_class
                            / num_samples_both_values)
                        diff_index_j = (
                            new_contingency_table[value_index_j, curr_class_index]
                            - expected_value_index_j_class)

                        edge_weight_curr_class = (
                            diff_index_i * (diff_index_i / expected_value_index_i_class)
                            + diff_index_j * (diff_index_j / expected_value_index_j_class))
                        weights[value_index_i, value_index_j] += edge_weight_curr_class

                    if new_values_num_seen.shape[0] > 2:
                        weights[value_index_i, value_index_j] /= (new_values_num_seen.shape[0] - 1.)
                    weights[value_index_j, value_index_i] = weights[value_index_i, value_index_j]
            return weights

        weights = _init_values_weights(new_contingency_table, new_values_num_seen)
        frac_split_cholesky = cls._solve_max_cut(weights)
        left_new_values, right_new_values = cls._generate_random_partition(frac_split_cholesky)

        left_orig_values, right_orig_values = cls._get_split_in_orig_values(new_to_orig_value_int,
                                                                            left_new_values,
                                                                            right_new_values)
        return left_orig_values, right_orig_values

    @staticmethod
    def _solve_max_cut(weights):
        def _solve_sdp(weights):
            # See Max Cut approximation given by Goemans and Williamson, 1995.
            var = cvx.Semidef(weights.shape[0])
            obj = cvx.Minimize(0.25 * cvx.trace(weights.T * var))

            constraints = [var == var.T, var >> 0]
            for i in range(weights.shape[0]):
                constraints.append(var[i, i] == 1)

            prob = cvx.Problem(obj, constraints)
            prob.solve(solver=cvx.SCS, verbose=False)
            return var.value

        fractional_split_squared = _solve_sdp(weights)
        # The solution should already be symmetric, but let's just make sure the approximations
        # didn't change that.
        sym_fractional_split_squared = 0.5 * (fractional_split_squared
                                              + fractional_split_squared.T)
        # We are interested in the Cholesky decomposition of the above matrix to finally choose a
        # random partition based on it. Detail: the above matrix may be singular, so not every
        # method works.
        permutation_matrix, lower_triang_matrix, _ = chol.chol_higham(sym_fractional_split_squared)

        # Note that lower_triang_matrix.T is upper triangular, but
        # frac_split_cholesky = np.dot(lower_triang_matrix.T, permutation_matrix)
        # is not necessarily upper triangular. Since we are only interested in decomposing
        # sym_fractional_split_squared = np.dot(frac_split_cholesky.T, frac_split_cholesky)
        # that is not a problem.
        return np.dot(lower_triang_matrix.T, permutation_matrix)

    @staticmethod
    def _generate_random_partition(frac_split_cholesky):
        random_vector = np.random.randn(frac_split_cholesky.shape[1])
        values_split = np.zeros((frac_split_cholesky.shape[1]), dtype=np.float64)
        for column_index in range(frac_split_cholesky.shape[1]):
            column = frac_split_cholesky[:, column_index]
            values_split[column_index] = np.dot(random_vector, column)
        values_split_bool = np.apply_along_axis(lambda x: x > 0.0, axis=0, arr=values_split)

        left_new_values = set()
        right_new_values = set()
        for new_value in range(frac_split_cholesky.shape[1]):
            if values_split_bool[new_value]:
                left_new_values.add(new_value)
            else:
                right_new_values.add(new_value)
        return left_new_values, right_new_values

    @staticmethod
    def _get_split_in_orig_values(new_to_orig_value_int, left_new_values, right_new_values):
        # Let's get the original values on each side of this partition
        left_orig_values = set(new_to_orig_value_int[left_new_value]
                               for left_new_value in left_new_values)
        right_orig_values = set(new_to_orig_value_int[right_new_value]
                                for right_new_value in right_new_values)
        return left_orig_values, right_orig_values



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                       PC-ext                                              ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class PCExt(Criterion):
    name = 'PC-ext'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the PC-ext criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                contingency_table = tree_node.contingency_tables[attrib_index].contingency_table
                values_num_samples = tree_node.contingency_tables[
                    attrib_index].values_num_samples
                (new_contingency_table,
                 new_num_samples_per_value,
                 new_index_to_old) = cls._group_values(contingency_table, values_num_samples)
                principal_component = cls._get_principal_component(
                    len(tree_node.valid_samples_indices),
                    new_contingency_table,
                    new_num_samples_per_value)
                inner_product_results = np.dot(principal_component, new_contingency_table.T)
                new_indices_order = inner_product_results.argsort()

                best_gini = float('+inf')
                best_left_values = set()
                best_right_values = set()
                left_values = set()
                right_values = set(new_indices_order)
                for metaindex, first_right in enumerate(new_indices_order):
                    curr_split_impurity = cls._calculate_split_gini_index(
                        new_contingency_table,
                        new_num_samples_per_value,
                        left_values,
                        right_values)
                    if curr_split_impurity < best_gini:
                        best_gini = curr_split_impurity
                        best_left_values = set(left_values)
                        best_right_values = set(right_values)
                    if left_values: # extended splits
                        last_left = new_indices_order[metaindex - 1]
                        left_values.remove(last_left)
                        right_values.add(last_left)
                        right_values.remove(first_right)
                        left_values.add(first_right)
                        curr_ext_split_impurity = cls._calculate_split_gini_index(
                            new_contingency_table,
                            new_num_samples_per_value,
                            left_values,
                            right_values)
                        if curr_ext_split_impurity < best_gini:
                            best_gini = curr_ext_split_impurity
                            best_left_values = set(left_values)
                            best_right_values = set(right_values)
                        right_values.remove(last_left)
                        left_values.add(last_left)
                        left_values.remove(first_right)
                        right_values.add(first_right)
                    right_values.remove(first_right)
                    left_values.add(first_right)
                (best_left_old_values,
                 best_right_old_values) = cls._change_split_to_use_old_values(best_left_values,
                                                                              best_right_values,
                                                                              new_index_to_old)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[best_left_old_values, best_right_old_values],
                          criterion_value=best_gini))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_gini,
                 last_left_value,
                 first_right_value) = cls._gini_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_gini))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _gini_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_gini = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                gini_value = cls._get_gini_value(class_num_left,
                                                 class_num_right,
                                                 num_left_samples,
                                                 num_right_samples)
                if gini_value < best_gini:
                    best_gini = gini_value
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_gini, best_last_left_value, best_first_right_value)

    @staticmethod
    def _get_num_samples_per_side(values_num_samples, left_values, right_values):
        """Returns two sets, each containing the values of a split side."""
        num_left_samples = sum(values_num_samples[value] for value in left_values)
        num_right_samples = sum(values_num_samples[value] for value in right_values)
        return  num_left_samples, num_right_samples

    @staticmethod
    def _get_num_samples_per_class_in_values(contingency_table, values):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_classes = contingency_table.shape[1]
        num_samples_per_class = [0] * num_classes
        for value in values:
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[
                    value, class_index]
        return num_samples_per_class

    @classmethod
    def _calculate_split_gini_index(cls, contingency_table, values_num_samples, left_values,
                                    right_values):
        """Calculates the weighted Gini index of a split."""
        num_left_samples, num_right_samples = cls._get_num_samples_per_side(
            values_num_samples, left_values, right_values)
        num_samples_per_class_left = cls._get_num_samples_per_class_in_values(
            contingency_table, left_values)
        num_samples_per_class_right = cls._get_num_samples_per_class_in_values(
            contingency_table, right_values)
        return cls._get_gini_value(num_samples_per_class_left, num_samples_per_class_right,
                                   num_left_samples, num_right_samples)

    @classmethod
    def _get_gini_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                        num_left_samples, num_right_samples):
        """Calculates the weighted Gini index of a split."""
        num_samples = num_left_samples + num_right_samples
        left_gini = cls._calculate_node_gini_index(num_left_samples, num_samples_per_class_left)
        right_gini = cls._calculate_node_gini_index(num_right_samples, num_samples_per_class_right)
        return ((num_left_samples / num_samples) * left_gini +
                (num_right_samples / num_samples) * right_gini)

    @staticmethod
    def _calculate_node_gini_index(num_split_samples, num_samples_per_class_in_split):
        """Calculates the Gini index of a node."""
        if not num_split_samples:
            return 1.0
        gini_index = 1.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            gini_index -= (curr_class_num_samples / num_split_samples)**2
        return gini_index

    @classmethod
    def _group_values(cls, contingency_table, values_num_samples):
        """Groups values that have the same class probability vector. Remove empty values."""
        (interm_to_orig_value_int,
         interm_contingency_table,
         interm_values_num_samples) = cls._remove_empty_values(contingency_table,
                                                               values_num_samples)
        prob_matrix_transposed = np.divide(interm_contingency_table.T, interm_values_num_samples)
        prob_matrix = prob_matrix_transposed.T
        row_order = np.lexsort(prob_matrix_transposed[::-1])
        compared_index = row_order[0]
        new_index_to_old = [[interm_to_orig_value_int[compared_index]]]
        for interm_index in row_order[1:]:
            if np.allclose(prob_matrix[compared_index], prob_matrix[interm_index]):
                new_index_to_old[-1].append(interm_to_orig_value_int[interm_index])
            else:
                compared_index = interm_index
                new_index_to_old.append([interm_to_orig_value_int[compared_index]])
        new_num_values = len(new_index_to_old)
        num_classes = interm_contingency_table.shape[1]
        new_contingency_table = np.zeros((new_num_values, num_classes), dtype=int)
        new_num_samples_per_value = np.zeros((new_num_values), dtype=int)
        for new_index, old_indices in enumerate(new_index_to_old):
            new_contingency_table[new_index] = np.sum(contingency_table[old_indices, :], axis=0)
            new_num_samples_per_value[new_index] = np.sum(values_num_samples[old_indices])
        return new_contingency_table, new_num_samples_per_value, new_index_to_old

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @staticmethod
    def _change_split_to_use_old_values(new_left, new_right, new_index_to_old):
        """Change split values to use indices of original contingency table."""
        left_old_values = set()
        for new_index in new_left:
            left_old_values |= set(new_index_to_old[new_index])
        right_old_values = set()
        for new_index in new_right:
            right_old_values |= set(new_index_to_old[new_index])
        return left_old_values, right_old_values

    @classmethod
    def _get_principal_component(cls, num_samples, contingency_table, values_num_samples):
        """Returns the principal component of the weighted covariance matrix."""
        num_samples_per_class = cls._get_num_samples_per_class(contingency_table)
        avg_prob_per_class = np.divide(num_samples_per_class, num_samples)
        prob_matrix = contingency_table / values_num_samples[:, None]
        diff_prob_matrix = (prob_matrix - avg_prob_per_class).T
        weight_diff_prob = diff_prob_matrix * values_num_samples[None, :]
        weighted_squared_diff_prob_matrix = np.dot(weight_diff_prob, diff_prob_matrix.T)
        weighted_covariance_matrix = (1/(num_samples - 1)) * weighted_squared_diff_prob_matrix
        eigenvalues, eigenvectors = np.linalg.eigh(weighted_covariance_matrix)
        index_largest_eigenvalue = np.argmax(np.square(eigenvalues))
        return eigenvectors[:, index_largest_eigenvalue]

    @staticmethod
    def _get_num_samples_per_class(contingency_table):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_values, num_classes = contingency_table.shape
        num_samples_per_class = [0] * num_classes
        for value in range(num_values):
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[value, class_index]
        return num_samples_per_class



#################################################################################################
#################################################################################################
###                                                                                           ###
###                             CONDITIONAL INFERENCE TREE PC-ext                             ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreePCExt(Criterion):
    """
    Conditional Inference Tree using PC-ext criterion to find best split. For reference,
    see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik
    & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006".
    """
    name = 'Conditional Inference Tree PC-ext'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the PC-ext criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            # Let's find the best split for this attribute using the PC-ext criterion.
            contingency_table = tree_node.contingency_tables[
                best_split.attrib_index].contingency_table
            values_num_samples = tree_node.contingency_tables[
                best_split.attrib_index].values_num_samples
            (new_contingency_table,
             new_num_samples_per_value,
             new_index_to_old) = cls._group_values(contingency_table, values_num_samples)
            principal_component = cls._get_principal_component(
                len(tree_node.valid_samples_indices),
                new_contingency_table,
                new_num_samples_per_value)
            inner_product_results = np.dot(principal_component, new_contingency_table.T)
            new_indices_order = inner_product_results.argsort()

            best_gini = float('+inf')
            best_left_values = set()
            best_right_values = set()
            left_values = set()
            right_values = set(new_indices_order)
            for metaindex, first_right in enumerate(new_indices_order):
                curr_split_impurity = cls._calculate_split_gini_index(
                    new_contingency_table,
                    new_num_samples_per_value,
                    left_values,
                    right_values)
                if curr_split_impurity < best_gini:
                    best_gini = curr_split_impurity
                    best_left_values = set(left_values)
                    best_right_values = set(right_values)
                if left_values: # extended splits
                    last_left = new_indices_order[metaindex - 1]
                    left_values.remove(last_left)
                    right_values.add(last_left)
                    right_values.remove(first_right)
                    left_values.add(first_right)
                    curr_ext_split_impurity = cls._calculate_split_gini_index(
                        new_contingency_table,
                        new_num_samples_per_value,
                        left_values,
                        right_values)
                    if curr_ext_split_impurity < best_gini:
                        best_gini = curr_ext_split_impurity
                        best_left_values = set(left_values)
                        best_right_values = set(right_values)
                    right_values.remove(last_left)
                    left_values.add(last_left)
                    left_values.remove(first_right)
                    right_values.add(first_right)
                right_values.remove(first_right)
                left_values.add(first_right)
            (best_left_old_values,
             best_right_old_values) = cls._change_split_to_use_old_values(best_left_values,
                                                                          best_right_values,
                                                                          new_index_to_old)
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[best_left_old_values, best_right_old_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @classmethod
    def _group_values(cls, contingency_table, values_num_samples):
        """Groups values that have the same class probability vector. Remove empty values."""
        (interm_to_orig_value_int,
         interm_contingency_table,
         interm_values_num_samples) = cls._remove_empty_values(contingency_table,
                                                               values_num_samples)
        prob_matrix_transposed = np.divide(interm_contingency_table.T, interm_values_num_samples)
        prob_matrix = prob_matrix_transposed.T
        row_order = np.lexsort(prob_matrix_transposed[::-1])
        compared_index = row_order[0]
        new_index_to_old = [[interm_to_orig_value_int[compared_index]]]
        for mid_index in row_order[1:]:
            if np.allclose(prob_matrix[compared_index], prob_matrix[mid_index]):
                new_index_to_old[-1].append(interm_to_orig_value_int[mid_index])
            else:
                compared_index = mid_index
                new_index_to_old.append([interm_to_orig_value_int[compared_index]])
        new_num_values = len(new_index_to_old)
        num_classes = interm_contingency_table.shape[1]
        new_contingency_table = np.zeros((new_num_values, num_classes), dtype=int)
        new_num_samples_per_value = np.zeros((new_num_values), dtype=int)
        for new_index, old_indices in enumerate(new_index_to_old):
            new_contingency_table[new_index] = np.sum(contingency_table[old_indices, :], axis=0)
            new_num_samples_per_value[new_index] = np.sum(values_num_samples[old_indices])
        return new_contingency_table, new_num_samples_per_value, new_index_to_old

    @classmethod
    def _get_principal_component(cls, num_samples, contingency_table, values_num_samples):
        """Returns the principal component of the weighted covariance matrix."""
        num_samples_per_class = cls._get_num_samples_per_class(contingency_table)
        avg_prob_per_class = np.divide(num_samples_per_class, num_samples)
        prob_matrix = contingency_table / values_num_samples[:, None]
        diff_prob_matrix = (prob_matrix - avg_prob_per_class).T
        weight_diff_prob = diff_prob_matrix * values_num_samples[None, :]
        weighted_squared_diff_prob_matrix = np.dot(weight_diff_prob, diff_prob_matrix.T)
        weighted_covariance_matrix = (1/(num_samples - 1)) * weighted_squared_diff_prob_matrix
        eigenvalues, eigenvectors = np.linalg.eigh(weighted_covariance_matrix)
        index_largest_eigenvalue = np.argmax(np.square(eigenvalues))
        return eigenvectors[:, index_largest_eigenvalue]

    @staticmethod
    def _get_num_samples_per_side(values_num_samples, left_values, right_values):
        """Returns two sets, each containing the values of a split side."""
        num_left_samples = sum(values_num_samples[value] for value in left_values)
        num_right_samples = sum(values_num_samples[value] for value in right_values)
        return  num_left_samples, num_right_samples

    @staticmethod
    def _get_num_samples_per_class_in_values(contingency_table, values):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_classes = contingency_table.shape[1]
        num_samples_per_class = [0] * num_classes
        for value in values:
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[
                    value, class_index]
        return num_samples_per_class

    @staticmethod
    def _get_num_samples_per_class(contingency_table):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_values, num_classes = contingency_table.shape
        num_samples_per_class = [0] * num_classes
        for value in range(num_values):
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[value, class_index]
        return num_samples_per_class

    @classmethod
    def _calculate_split_gini_index(cls, contingency_table, values_num_samples, left_values,
                                    right_values):
        """Calculates the weighted Gini index of a split."""
        num_left_samples, num_right_samples = cls._get_num_samples_per_side(
            values_num_samples, left_values, right_values)
        num_samples_per_class_left = cls._get_num_samples_per_class_in_values(
            contingency_table, left_values)
        num_samples_per_class_right = cls._get_num_samples_per_class_in_values(
            contingency_table, right_values)
        return cls._get_gini_value(num_samples_per_class_left, num_samples_per_class_right,
                                   num_left_samples, num_right_samples)

    @classmethod
    def _get_gini_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                        num_left_samples, num_right_samples):
        """Calculates the weighted Gini index of a split."""
        num_samples = num_left_samples + num_right_samples
        left_gini = cls._calculate_node_gini_index(num_left_samples, num_samples_per_class_left)
        right_gini = cls._calculate_node_gini_index(num_right_samples, num_samples_per_class_right)
        return ((num_left_samples / num_samples) * left_gini +
                (num_right_samples / num_samples) * right_gini)

    @staticmethod
    def _calculate_node_gini_index(num_split_samples, num_samples_per_class_in_split):
        """Calculates the Gini index of a node."""
        if not num_split_samples:
            return 1.0
        gini_index = 1.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            gini_index -= (curr_class_num_samples / num_split_samples)**2
        return gini_index

    @staticmethod
    def _change_split_to_use_old_values(new_left, new_right, new_index_to_old):
        """Change split values to use indices of original contingency table."""
        left_old_values = set()
        for new_index in new_left:
            left_old_values |= set(new_index_to_old[new_index])
        right_old_values = set()
        for new_index in new_right:
            right_old_values |= set(new_index_to_old[new_index])
        return left_old_values, right_old_values



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                     HYPERCUBE COVER                                       ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class HypercubeCover(Criterion):
    """Hypercube Cover criterion."""
    name = 'Hypercube Cover'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the Hypercube Cover
        criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                best_children_gini_gain = float('+inf')
                best_left_values = set()
                best_right_values = set()
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                for (set_left_classes,
                     set_right_classes) in cls._generate_superclasses(
                         tree_node.class_index_num_samples):
                    (superclass_contingency_table,
                     superclass_index_num_samples) = cls._get_superclass_contingency_table(
                         tree_node.contingency_tables[attrib_index].contingency_table,
                         tree_node.contingency_tables[attrib_index].values_num_samples,
                         set_left_classes,
                         set_right_classes)
                    (curr_gini_gain,
                     left_values,
                     right_values) = cls._two_class_trick(
                         tree_node.class_index_num_samples,
                         superclass_index_num_samples,
                         values_seen,
                         tree_node.contingency_tables[attrib_index].contingency_table,
                         tree_node.contingency_tables[attrib_index].values_num_samples,
                         superclass_contingency_table,
                         len(tree_node.valid_samples_indices))

                    if curr_gini_gain < best_children_gini_gain:
                        best_children_gini_gain = curr_gini_gain
                        best_left_values = left_values
                        best_right_values = right_values
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[best_left_values, best_right_values],
                          criterion_value=best_children_gini_gain))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_gini,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_gini))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @staticmethod
    def _generate_superclasses(class_index_num_samples):
        # We only need to look at superclasses of up to (len(class_index_num_samples)/2 + 1)
        # elements because of symmetry! The subsets we are not choosing are complements of the ones
        # chosen.
        non_empty_classes = set([])
        for class_index, class_num_samples in enumerate(class_index_num_samples):
            if class_num_samples > 0:
                non_empty_classes.add(class_index)
        number_non_empty_classes = len(non_empty_classes)

        for left_classes in itertools.chain.from_iterable(
                itertools.combinations(non_empty_classes, size_left_superclass)
                for size_left_superclass in range(1, number_non_empty_classes // 2 + 1)):
            set_left_classes = set(left_classes)
            set_right_classes = non_empty_classes - set_left_classes
            if not set_left_classes or not set_right_classes:
                # A valid split must have at least one sample in each side
                continue
            yield set_left_classes, set_right_classes

    @staticmethod
    def _get_superclass_contingency_table(contingency_table, values_num_samples, set_left_classes,
                                          set_right_classes):
        superclass_contingency_table = np.zeros((contingency_table.shape[0], 2), dtype=float)
        superclass_index_num_samples = [0, 0]
        for value, value_num_samples in enumerate(values_num_samples):
            if value_num_samples == 0:
                continue
            for class_index in set_left_classes:
                superclass_index_num_samples[0] += contingency_table[value][class_index]
                superclass_contingency_table[value][0] += contingency_table[value][class_index]
            for class_index in set_right_classes:
                superclass_index_num_samples[1] += contingency_table[value][class_index]
                superclass_contingency_table[value][1] += contingency_table[value][class_index]
        return superclass_contingency_table, superclass_index_num_samples

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_gini = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                gini_value = cls._calculate_children_gini_index(num_left_samples,
                                                                class_num_left,
                                                                num_right_samples,
                                                                class_num_right)
                if gini_value < best_gini:
                    best_gini = gini_value
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_gini, best_last_left_value, best_first_right_value)

    @staticmethod
    def _calculate_gini_index(side_num, class_num_side):
        gini_index = 1.0
        for curr_class_num_side in class_num_side:
            if curr_class_num_side > 0:
                gini_index -= (curr_class_num_side / side_num) ** 2
        return gini_index

    @classmethod
    def _calculate_children_gini_index(cls, left_num, class_num_left, right_num, class_num_right):
        left_split_gini_index = cls._calculate_gini_index(left_num, class_num_left)
        right_split_gini_index = cls._calculate_gini_index(right_num, class_num_right)
        children_gini_index = ((left_num * left_split_gini_index
                                + right_num * right_split_gini_index)
                               / (left_num + right_num))
        return children_gini_index

    @classmethod
    def _two_class_trick(cls, class_index_num_samples, superclass_index_num_samples, values_seen,
                         contingency_table, values_num_samples, superclass_contingency_table,
                         num_total_valid_samples):
        # TESTED!
        def _get_non_empty_superclass_indices(superclass_index_num_samples):
            # TESTED!
            first_non_empty_superclass = None
            second_non_empty_superclass = None
            for superclass_index, superclass_num_samples in enumerate(superclass_index_num_samples):
                if superclass_num_samples > 0:
                    if first_non_empty_superclass is None:
                        first_non_empty_superclass = superclass_index
                    else:
                        second_non_empty_superclass = superclass_index
                        break
            return first_non_empty_superclass, second_non_empty_superclass

        def _calculate_value_class_ratio(values_seen, values_num_samples,
                                         superclass_contingency_table, non_empty_class_indices):
            # TESTED!
            value_class_ratio = [] # [(value, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = superclass_contingency_table[
                    curr_value][second_class_index]
                value_class_ratio.append(
                    (curr_value, number_second_non_empty / values_num_samples[curr_value]))
            value_class_ratio.sort(key=lambda tup: tup[1])
            return value_class_ratio


        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_superclass,
         second_non_empty_superclass) = _get_non_empty_superclass_indices(
             superclass_index_num_samples)
        if first_non_empty_superclass is None or second_non_empty_superclass is None:
            return (float('+inf'), {0}, set())

        value_class_ratio = _calculate_value_class_ratio(values_seen,
                                                         values_num_samples,
                                                         superclass_contingency_table,
                                                         (first_non_empty_superclass,
                                                          second_non_empty_superclass))

        best_split_children_gini_gain = float('+inf')
        best_last_left_index = 0

        num_right_samples = num_total_valid_samples
        class_num_right = np.copy(class_index_num_samples)
        num_left_samples = 0
        class_num_left = np.zeros(class_num_right.shape, dtype=int)

        for last_left_index, (last_left_value, _) in enumerate(value_class_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            num_left_samples += num_samples_last_left_value
            num_right_samples -= num_samples_last_left_value
            class_num_left += contingency_table[last_left_value]
            class_num_right -= contingency_table[last_left_value]

            curr_children_gini_index = cls._calculate_children_gini_index(num_left_samples,
                                                                          class_num_left,
                                                                          num_right_samples,
                                                                          class_num_right)
            if curr_children_gini_index < best_split_children_gini_gain:
                best_split_children_gini_gain = curr_children_gini_index
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set(tup[0] for tup in value_class_ratio[:best_last_left_index + 1])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_children_gini_gain, set_left_values, set_right_values)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                        CONDITIONAL INFERENCE TREE HYPERCUBE COVER                         ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeHypercubeCover(Criterion):
    """
    Conditional Inference Tree using Hypercube Cover criterion to find best split. For reference,
    see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn, K. Hornik
    & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,2006".
    """
    name = 'Conditional Inference Tree Hypercube Cover'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the Hypercube Cover criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            best_children_gini_gain = float('+inf')
            best_left_values = set()
            best_right_values = set()
            values_seen = cls._get_values_seen(
                tree_node.contingency_tables[best_split.attrib_index].values_num_samples)
            for (set_left_classes,
                 set_right_classes) in cls._generate_superclasses(
                     tree_node.class_index_num_samples):
                (superclass_contingency_table,
                 superclass_index_num_samples) = cls._get_superclass_contingency_table(
                     tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                     tree_node.contingency_tables[best_split.attrib_index].values_num_samples,
                     set_left_classes,
                     set_right_classes)
                (curr_gini_gain,
                 left_values,
                 right_values) = cls._two_class_trick(
                     tree_node.class_index_num_samples,
                     superclass_index_num_samples,
                     values_seen,
                     tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                     tree_node.contingency_tables[best_split.attrib_index].values_num_samples,
                     superclass_contingency_table,
                     len(tree_node.valid_samples_indices))
                if curr_gini_gain < best_children_gini_gain:
                    best_children_gini_gain = curr_gini_gain
                    best_left_values = left_values
                    best_right_values = right_values
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[best_left_values, best_right_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _generate_superclasses(class_index_num_samples):
        # We only need to look at superclasses of up to (len(class_index_num_samples)/2 + 1)
        # elements because of symmetry! The subsets we are not choosing are complements of the ones
        # chosen.
        non_empty_classes = set([])
        for class_index, class_num_samples in enumerate(class_index_num_samples):
            if class_num_samples > 0:
                non_empty_classes.add(class_index)
        number_non_empty_classes = len(non_empty_classes)

        for left_classes in itertools.chain.from_iterable(
                itertools.combinations(non_empty_classes, size_left_superclass)
                for size_left_superclass in range(1, number_non_empty_classes // 2 + 1)):
            set_left_classes = set(left_classes)
            set_right_classes = non_empty_classes - set_left_classes
            if not set_left_classes or not set_right_classes:
                # A valid split must have at least one sample in each side
                continue
            yield set_left_classes, set_right_classes

    @staticmethod
    def _get_superclass_contingency_table(contingency_table, values_num_samples, set_left_classes,
                                          set_right_classes):
        superclass_contingency_table = np.zeros((contingency_table.shape[0], 2), dtype=float)
        superclass_index_num_samples = [0, 0]
        for value, value_num_samples in enumerate(values_num_samples):
            if value_num_samples == 0:
                continue
            for class_index in set_left_classes:
                superclass_index_num_samples[0] += contingency_table[value][class_index]
                superclass_contingency_table[value][0] += contingency_table[value][class_index]
            for class_index in set_right_classes:
                superclass_index_num_samples[1] += contingency_table[value][class_index]
                superclass_contingency_table[value][1] += contingency_table[value][class_index]
        return superclass_contingency_table, superclass_index_num_samples

    @staticmethod
    def _calculate_gini_index(side_num, class_num_side):
        gini_index = 1.0
        for curr_class_num_side in class_num_side:
            if curr_class_num_side > 0:
                gini_index -= (curr_class_num_side / side_num) ** 2
        return gini_index

    @classmethod
    def _calculate_children_gini_index(cls, left_num, class_num_left, right_num, class_num_right):
        left_split_gini_index = cls._calculate_gini_index(left_num, class_num_left)
        right_split_gini_index = cls._calculate_gini_index(right_num, class_num_right)
        children_gini_index = ((left_num * left_split_gini_index
                                + right_num * right_split_gini_index)
                               / (left_num + right_num))
        return children_gini_index

    @classmethod
    def _two_class_trick(cls, class_index_num_samples, superclass_index_num_samples, values_seen,
                         contingency_table, values_num_samples, superclass_contingency_table,
                         num_total_valid_samples):
        # TESTED!
        def _get_non_empty_superclass_indices(superclass_index_num_samples):
            # TESTED!
            first_non_empty_superclass = None
            second_non_empty_superclass = None
            for superclass_index, superclass_num_samples in enumerate(superclass_index_num_samples):
                if superclass_num_samples > 0:
                    if first_non_empty_superclass is None:
                        first_non_empty_superclass = superclass_index
                    else:
                        second_non_empty_superclass = superclass_index
                        break
            return first_non_empty_superclass, second_non_empty_superclass

        def _calculate_value_class_ratio(values_seen, values_num_samples,
                                         superclass_contingency_table, non_empty_class_indices):
            # TESTED!
            value_class_ratio = [] # [(value, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = superclass_contingency_table[
                    curr_value][second_class_index]
                value_class_ratio.append(
                    (curr_value, number_second_non_empty / values_num_samples[curr_value]))
            value_class_ratio.sort(key=lambda tup: tup[1])
            return value_class_ratio


        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_superclass,
         second_non_empty_superclass) = _get_non_empty_superclass_indices(
             superclass_index_num_samples)
        if first_non_empty_superclass is None or second_non_empty_superclass is None:
            return (float('+inf'), {0}, set())

        value_class_ratio = _calculate_value_class_ratio(values_seen,
                                                         values_num_samples,
                                                         superclass_contingency_table,
                                                         (first_non_empty_superclass,
                                                          second_non_empty_superclass))

        best_split_children_gini_gain = float('+inf')
        best_last_left_index = 0

        num_right_samples = num_total_valid_samples
        class_num_right = np.copy(class_index_num_samples)
        num_left_samples = 0
        class_num_left = np.zeros(class_num_right.shape, dtype=int)

        for last_left_index, (last_left_value, _) in enumerate(value_class_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            num_left_samples += num_samples_last_left_value
            num_right_samples -= num_samples_last_left_value
            class_num_left += contingency_table[last_left_value]
            class_num_right -= contingency_table[last_left_value]

            curr_children_gini_index = cls._calculate_children_gini_index(num_left_samples,
                                                                          class_num_left,
                                                                          num_right_samples,
                                                                          class_num_right)
            if curr_children_gini_index < best_split_children_gini_gain:
                best_split_children_gini_gain = curr_children_gini_index
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set(tup[0] for tup in value_class_ratio[:best_last_left_index + 1])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_children_gini_gain, set_left_values, set_right_values)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                 LARGEST CLASS ALONE                                       ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class LargestClassAlone(Criterion):
    """Largest Class Alone criterion."""
    name = 'Largest Class Alone'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the Hypercube Cover
        criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                largest_class_index, _ = max(
                    enumerate(tree_node.class_index_num_samples), key=lambda x: x[1])
                (superclass_contingency_table,
                 superclass_index_num_samples) = cls._get_superclass_contingency_table(
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples,
                     tree_node.class_index_num_samples,
                     largest_class_index)
                (curr_gini_gain,
                 left_values,
                 right_values) = cls._two_class_trick(
                     tree_node.class_index_num_samples,
                     superclass_index_num_samples,
                     values_seen,
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples,
                     superclass_contingency_table,
                     len(tree_node.valid_samples_indices))
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_values, right_values],
                          criterion_value=curr_gini_gain))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_gini,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_gini))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_superclass_contingency_table(contingency_table, values_num_samples,
                                          class_index_num_samples, largest_classes_index):
        superclass_contingency_table = np.array(
            [contingency_table[:, largest_classes_index],
             values_num_samples - contingency_table[:, largest_classes_index]
            ]).T
        superclass_index_num_samples = [
            class_index_num_samples[largest_classes_index],
            sum(class_index_num_samples) - class_index_num_samples[largest_classes_index]]
        return superclass_contingency_table, superclass_index_num_samples

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_gini = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                gini_value = cls._calculate_children_gini_index(num_left_samples,
                                                                class_num_left,
                                                                num_right_samples,
                                                                class_num_right)
                if gini_value < best_gini:
                    best_gini = gini_value
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_gini, best_last_left_value, best_first_right_value)

    @staticmethod
    def _calculate_gini_index(side_num, class_num_side):
        gini_index = 1.0
        for curr_class_num_side in class_num_side:
            if curr_class_num_side > 0:
                gini_index -= (curr_class_num_side / side_num) ** 2
        return gini_index

    @classmethod
    def _calculate_children_gini_index(cls, left_num, class_num_left, right_num, class_num_right):
        left_split_gini_index = cls._calculate_gini_index(left_num, class_num_left)
        right_split_gini_index = cls._calculate_gini_index(right_num, class_num_right)
        children_gini_index = ((left_num * left_split_gini_index
                                + right_num * right_split_gini_index)
                               / (left_num + right_num))
        return children_gini_index

    @classmethod
    def _two_class_trick(cls, class_index_num_samples, superclass_index_num_samples, values_seen,
                         contingency_table, values_num_samples, superclass_contingency_table,
                         num_total_valid_samples):
        # TESTED!
        def _get_non_empty_superclass_indices(superclass_index_num_samples):
            # TESTED!
            first_non_empty_superclass = None
            second_non_empty_superclass = None
            for superclass_index, superclass_num_samples in enumerate(superclass_index_num_samples):
                if superclass_num_samples > 0:
                    if first_non_empty_superclass is None:
                        first_non_empty_superclass = superclass_index
                    else:
                        second_non_empty_superclass = superclass_index
                        break
            return first_non_empty_superclass, second_non_empty_superclass

        def _calculate_value_class_ratio(values_seen, values_num_samples,
                                         superclass_contingency_table, non_empty_class_indices):
            # TESTED!
            value_class_ratio = [] # [(value, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = superclass_contingency_table[
                    curr_value][second_class_index]
                value_class_ratio.append(
                    (curr_value, number_second_non_empty / values_num_samples[curr_value]))
            value_class_ratio.sort(key=lambda tup: tup[1])
            return value_class_ratio


        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_superclass,
         second_non_empty_superclass) = _get_non_empty_superclass_indices(
             superclass_index_num_samples)
        if first_non_empty_superclass is None or second_non_empty_superclass is None:
            return (float('+inf'), {0}, set())

        value_class_ratio = _calculate_value_class_ratio(values_seen,
                                                         values_num_samples,
                                                         superclass_contingency_table,
                                                         (first_non_empty_superclass,
                                                          second_non_empty_superclass))

        best_split_children_gini_gain = float('+inf')
        best_last_left_index = 0

        num_right_samples = num_total_valid_samples
        class_num_right = np.copy(class_index_num_samples)
        num_left_samples = 0
        class_num_left = np.zeros(class_num_right.shape, dtype=int)

        for last_left_index, (last_left_value, _) in enumerate(value_class_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            num_left_samples += num_samples_last_left_value
            num_right_samples -= num_samples_last_left_value
            class_num_left += contingency_table[last_left_value]
            class_num_right -= contingency_table[last_left_value]

            curr_children_gini_index = cls._calculate_children_gini_index(num_left_samples,
                                                                          class_num_left,
                                                                          num_right_samples,
                                                                          class_num_right)
            if curr_children_gini_index < best_split_children_gini_gain:
                best_split_children_gini_gain = curr_children_gini_index
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set(tup[0] for tup in value_class_ratio[:best_last_left_index + 1])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_children_gini_gain, set_left_values, set_right_values)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                       CONDITIONAL INFERENCE TREE LARGEST CLASS ALONE                      ###
###                                                                                           ###
#################################################################################################
#################################################################################################


class ConditionalInferenceTreeLargestClassAlone(Criterion):
    """
    Conditional Inference Tree using Largest Class Alone criterion to find best split. For
    reference, see "Unbiased Recursive Partitioning: A Conditional Inference Framework, T. Hothorn,
    K. Hornik & A. Zeileis. Journal of Computational and Graphical Statistics Vol. 15 , Iss. 3,
    2006".
    """
    name = 'Conditional Inference Tree Largest Class Alone'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, using the Conditional Inference Tree
        Framework to choose the best attribute and using the Hypercube Cover criterion to find the
        best split for it.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        use_chi2 = False
        for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
            if is_valid_attrib and cls._is_big_contingency_table(
                    tree_node.contingency_tables[attrib_index].values_num_samples,
                    tree_node.class_index_num_samples):
                use_chi2 = True
                break
        if use_chi2: # Use Chi²-test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_chi2_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_chi2_cdf))
        else: # Use Conditional Inference Trees' test
            for attrib_index, is_valid_attrib in enumerate(tree_node.valid_nominal_attribute):
                if is_valid_attrib:
                    curr_c_quad_cdf = cls._calculate_c_quad_cdf(
                        tree_node.contingency_tables[attrib_index].contingency_table,
                        tree_node.contingency_tables[attrib_index].values_num_samples,
                        tree_node.class_index_num_samples,
                        len(tree_node.valid_samples_indices))
                    # Split will be calculated later
                    best_splits_per_attrib.append(Split(attrib_index=attrib_index,
                                                        splits_values=[],
                                                        criterion_value=curr_c_quad_cdf))
        if best_splits_per_attrib:
            best_split = max(best_splits_per_attrib, key=lambda split: split.criterion_value)
            values_seen = cls._get_values_seen(
                tree_node.contingency_tables[best_split.attrib_index].values_num_samples)
            largest_class_index, _ = max(
                enumerate(tree_node.class_index_num_samples), key=lambda x: x[1])
            (superclass_contingency_table,
             superclass_index_num_samples) = cls._get_superclass_contingency_table(
                 tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                 tree_node.contingency_tables[best_split.attrib_index].values_num_samples,
                 tree_node.class_index_num_samples,
                 largest_class_index)
            (_,
             left_values,
             right_values) = cls._two_class_trick(
                 tree_node.class_index_num_samples,
                 superclass_index_num_samples,
                 values_seen,
                 tree_node.contingency_tables[best_split.attrib_index].contingency_table,
                 tree_node.contingency_tables[best_split.attrib_index].values_num_samples,
                 superclass_contingency_table,
                 len(tree_node.valid_samples_indices))
            return Split(attrib_index=best_split.attrib_index,
                         splits_values=[left_values, right_values],
                         criterion_value=best_split.criterion_value)
        return Split()

    @classmethod
    def _is_big_contingency_table(cls, values_num_samples, class_index_num_samples):
        num_values_seen = sum(value_num_samples > 0 for value_num_samples in values_num_samples)
        num_classes_seen = sum(class_num_samples > 0
                               for class_num_samples in class_index_num_samples)
        return num_values_seen * num_classes_seen > BIG_CONTINGENCY_TABLE_THRESHOLD

    @classmethod
    def _get_chi_square_test_p_value(cls, contingency_table, values_num_samples,
                                     class_index_num_samples):
        classes_seen = set(class_index for class_index, class_num_samples
                           in enumerate(class_index_num_samples) if class_num_samples > 0)
        num_classes = len(classes_seen)
        if num_classes == 1:
            return 0.0

        num_values = sum(num_samples > 0 for num_samples in values_num_samples)
        num_samples = sum(num_samples for num_samples in values_num_samples)
        curr_chi_square_value = 0.0
        for value, value_num_sample in enumerate(values_num_samples):
            if value_num_sample == 0:
                continue
            for class_index in classes_seen:
                expected_value_class = (
                    values_num_samples[value] * class_index_num_samples[class_index] / num_samples)
                diff = contingency_table[value][class_index] - expected_value_class
                curr_chi_square_value += diff * (diff / expected_value_class)
        return 1. - scipy.stats.chi2.cdf(x=curr_chi_square_value,
                                         df=((num_classes - 1) * (num_values - 1)))

    @classmethod
    def _calculate_c_quad_cdf(cls, contingency_table, values_num_samples, class_index_num_samples,
                              num_valid_samples):
        def _calculate_expected_value_h(class_index_num_samples, num_valid_samples):
            return (1./num_valid_samples) * np.array(class_index_num_samples)

        def _calculate_covariance_h(expected_value_h, class_index_num_samples, num_valid_samples):
            num_classes = len(class_index_num_samples)
            covariance_h = np.zeros((num_classes, num_classes))
            for class_index, class_num_samples in enumerate(class_index_num_samples):
                if class_num_samples:
                    curr_class_one_hot_encoding = np.zeros((num_classes))
                    curr_class_one_hot_encoding[class_index] = 1.
                    diff = curr_class_one_hot_encoding - expected_value_h
                    covariance_h += class_num_samples * np.outer(diff, diff)
            return covariance_h / num_valid_samples

        def _calculate_mu_j(values_num_samples, expected_value_h):
            return np.outer(values_num_samples, expected_value_h).flatten(order='F')

        def _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h):
            values_num_samples_correct_dim = values_num_samples.reshape(
                (values_num_samples.shape[0], 1))
            return (((num_valid_samples / (num_valid_samples - 1))
                     * np.kron(covariance_h, np.diag(values_num_samples)))
                    - ((1 / (num_valid_samples - 1))
                       * np.kron(covariance_h,
                                 np.kron(values_num_samples_correct_dim,
                                         values_num_samples_correct_dim.transpose()))))


        expected_value_h = _calculate_expected_value_h(class_index_num_samples, num_valid_samples)
        covariance_h = _calculate_covariance_h(expected_value_h,
                                               class_index_num_samples,
                                               num_valid_samples)
        mu_j = _calculate_mu_j(values_num_samples, expected_value_h)
        sigma_j = _calculate_sigma_j(values_num_samples, num_valid_samples, covariance_h)

        temp_diff = contingency_table.flatten(order='F') - mu_j

        curr_rcond = 1e-15
        while True:
            try:
                sigma_j_pinv = np.linalg.pinv(sigma_j)
                sigma_j_rank = np.linalg.matrix_rank(sigma_j)
                break
            except np.linalg.linalg.LinAlgError:
                # Happens when sigma_j is (very) badly conditioned
                pass
            try:
                (sigma_j_pinv, sigma_j_rank) = scipy.linalg.pinv(sigma_j, return_rank=True)
                break
            except:
                # Happens when sigma_j is (very) badly conditioned
                curr_rcond *= 10.
                if curr_rcond > 1e-6:
                    # We give up on this attribute
                    print('Warning: attribute has sigma_j matrix that is not decomposable in SVD.')
                    return float('-inf')

        c_quad = np.dot(temp_diff, np.dot(sigma_j_pinv, temp_diff.transpose()))
        return scipy.stats.chi2.cdf(x=c_quad, df=sigma_j_rank)

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_superclass_contingency_table(contingency_table, values_num_samples,
                                          class_index_num_samples, largest_classes_index):
        superclass_contingency_table = np.array(
            [contingency_table[:, largest_classes_index],
             values_num_samples - contingency_table[:, largest_classes_index]
            ]).T
        superclass_index_num_samples = [
            class_index_num_samples[largest_classes_index],
            sum(class_index_num_samples) - class_index_num_samples[largest_classes_index]]
        return superclass_contingency_table, superclass_index_num_samples

    @staticmethod
    def _calculate_gini_index(side_num, class_num_side):
        gini_index = 1.0
        for curr_class_num_side in class_num_side:
            if curr_class_num_side > 0:
                gini_index -= (curr_class_num_side / side_num) ** 2
        return gini_index

    @classmethod
    def _calculate_children_gini_index(cls, left_num, class_num_left, right_num, class_num_right):
        left_split_gini_index = cls._calculate_gini_index(left_num, class_num_left)
        right_split_gini_index = cls._calculate_gini_index(right_num, class_num_right)
        children_gini_index = ((left_num * left_split_gini_index
                                + right_num * right_split_gini_index)
                               / (left_num + right_num))
        return children_gini_index

    @classmethod
    def _two_class_trick(cls, class_index_num_samples, superclass_index_num_samples, values_seen,
                         contingency_table, values_num_samples, superclass_contingency_table,
                         num_total_valid_samples):
        # TESTED!
        def _get_non_empty_superclass_indices(superclass_index_num_samples):
            # TESTED!
            first_non_empty_superclass = None
            second_non_empty_superclass = None
            for superclass_index, superclass_num_samples in enumerate(superclass_index_num_samples):
                if superclass_num_samples > 0:
                    if first_non_empty_superclass is None:
                        first_non_empty_superclass = superclass_index
                    else:
                        second_non_empty_superclass = superclass_index
                        break
            return first_non_empty_superclass, second_non_empty_superclass

        def _calculate_value_class_ratio(values_seen, values_num_samples,
                                         superclass_contingency_table, non_empty_class_indices):
            # TESTED!
            value_class_ratio = [] # [(value, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = superclass_contingency_table[
                    curr_value][second_class_index]
                value_class_ratio.append(
                    (curr_value, number_second_non_empty / values_num_samples[curr_value]))
            value_class_ratio.sort(key=lambda tup: tup[1])
            return value_class_ratio


        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_superclass,
         second_non_empty_superclass) = _get_non_empty_superclass_indices(
             superclass_index_num_samples)
        if first_non_empty_superclass is None or second_non_empty_superclass is None:
            return (float('+inf'), {0}, set())

        value_class_ratio = _calculate_value_class_ratio(values_seen,
                                                         values_num_samples,
                                                         superclass_contingency_table,
                                                         (first_non_empty_superclass,
                                                          second_non_empty_superclass))

        best_split_children_gini_gain = float('+inf')
        best_last_left_index = 0

        num_right_samples = num_total_valid_samples
        class_num_right = np.copy(class_index_num_samples)
        num_left_samples = 0
        class_num_left = np.zeros(class_num_right.shape, dtype=int)

        for last_left_index, (last_left_value, _) in enumerate(value_class_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            num_left_samples += num_samples_last_left_value
            num_right_samples -= num_samples_last_left_value
            class_num_left += contingency_table[last_left_value]
            class_num_right -= contingency_table[last_left_value]

            curr_children_gini_index = cls._calculate_children_gini_index(num_left_samples,
                                                                          class_num_left,
                                                                          num_right_samples,
                                                                          class_num_right)
            if curr_children_gini_index < best_split_children_gini_gain:
                best_split_children_gini_gain = curr_children_gini_index
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set(tup[0] for tup in value_class_ratio[:best_last_left_index + 1])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_children_gini_gain, set_left_values, set_right_values)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                     PC-ext-Entropy                                        ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class PCExtEntropy(Criterion):
    """PC-ext criterion using the Entropy impurity measure."""
    name = 'PC-ext-Entropy'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the PC-ext criterion.

        Uses the Information Gain impurity measure.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                contingency_table = tree_node.contingency_tables[attrib_index].contingency_table
                values_num_samples = tree_node.contingency_tables[
                    attrib_index].values_num_samples
                (new_contingency_table,
                 new_num_samples_per_value,
                 new_index_to_old) = cls._group_values(contingency_table, values_num_samples)
                principal_component = cls._get_principal_component(
                    len(tree_node.valid_samples_indices),
                    new_contingency_table,
                    new_num_samples_per_value)
                inner_product_results = np.dot(principal_component, new_contingency_table.T)
                new_indices_order = inner_product_results.argsort()

                best_entropy = float('+inf')
                best_left_values = set()
                best_right_values = set()
                left_values = set()
                right_values = set(new_indices_order)
                for metaindex, first_right in enumerate(new_indices_order):
                    curr_split_impurity = cls._calculate_information_gain(
                        new_contingency_table,
                        new_num_samples_per_value,
                        left_values,
                        right_values)
                    if curr_split_impurity < best_entropy:
                        best_entropy = curr_split_impurity
                        best_left_values = set(left_values)
                        best_right_values = set(right_values)
                    if left_values: # extended splits
                        last_left = new_indices_order[metaindex - 1]
                        left_values.remove(last_left)
                        right_values.add(last_left)
                        right_values.remove(first_right)
                        left_values.add(first_right)
                        curr_ext_split_impurity = cls._calculate_information_gain(
                            new_contingency_table,
                            new_num_samples_per_value,
                            left_values,
                            right_values)
                        if curr_ext_split_impurity < best_entropy:
                            best_entropy = curr_ext_split_impurity
                            best_left_values = set(left_values)
                            best_right_values = set(right_values)
                        right_values.remove(last_left)
                        left_values.add(last_left)
                        left_values.remove(first_right)
                        right_values.add(first_right)
                    right_values.remove(first_right)
                    left_values.add(first_right)
                (best_left_old_values,
                 best_right_old_values) = cls._change_split_to_use_old_values(best_left_values,
                                                                              best_right_values,
                                                                              new_index_to_old)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[best_left_old_values, best_right_old_values],
                          criterion_value=best_entropy))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_entropy,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_entropy))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @classmethod
    def _calculate_information_gain(cls, contingency_table, num_samples_per_value, left_values,
                                    right_values):
        """Calculates the Information Gain of the given binary split."""
        num_left_samples, num_right_samples = cls._get_num_samples_per_side(
            num_samples_per_value, left_values, right_values)
        num_samples_per_class_left = cls._get_num_samples_per_class_in_values(
            contingency_table, left_values)
        num_samples_per_class_right = cls._get_num_samples_per_class_in_values(
            contingency_table, right_values)
        return cls._get_information_gain_value(num_samples_per_class_left,
                                               num_samples_per_class_right,
                                               num_left_samples,
                                               num_right_samples)

    @classmethod
    def _get_information_gain_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                                    num_left_samples, num_right_samples):
        """Calculates the weighted Information Gain of a split."""
        num_samples = num_left_samples + num_right_samples
        left_entropy = cls._calculate_node_information(
            num_left_samples, num_samples_per_class_left)
        right_entropy = cls._calculate_node_information(
            num_right_samples, num_samples_per_class_right)
        split_information_gain = ((num_left_samples / num_samples) * left_entropy +
                                  (num_right_samples / num_samples) * right_entropy)
        return split_information_gain

    @classmethod
    def _calculate_node_information(cls, num_split_samples, num_samples_per_class_in_split):
        """Calculates the Information of the node given by the values."""
        information = 0.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            if curr_class_num_samples != 0:
                curr_frequency = curr_class_num_samples / num_split_samples
                information -= curr_frequency * math.log2(curr_frequency)
        return information

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_entropy = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                information_gain = cls._get_information_gain_value(class_num_left,
                                                                   class_num_right,
                                                                   num_left_samples,
                                                                   num_right_samples)
                if information_gain < best_entropy:
                    best_entropy = information_gain
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_entropy, best_last_left_value, best_first_right_value)

    @staticmethod
    def _get_num_samples_per_side(values_num_samples, left_values, right_values):
        """Returns two sets, each containing the values of a split side."""
        num_left_samples = sum(values_num_samples[value] for value in left_values)
        num_right_samples = sum(values_num_samples[value] for value in right_values)
        return  num_left_samples, num_right_samples

    @staticmethod
    def _get_num_samples_per_class_in_values(contingency_table, values):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_classes = contingency_table.shape[1]
        num_samples_per_class = [0] * num_classes
        for value in values:
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[
                    value, class_index]
        return num_samples_per_class

    @classmethod
    def _group_values(cls, contingency_table, values_num_samples):
        """Groups values that have the same class probability vector. Remove empty values."""
        (interm_to_orig_value_int,
         interm_contingency_table,
         interm_values_num_samples) = cls._remove_empty_values(contingency_table,
                                                               values_num_samples)
        prob_matrix_transposed = np.divide(interm_contingency_table.T, interm_values_num_samples)
        prob_matrix = prob_matrix_transposed.T
        row_order = np.lexsort(prob_matrix_transposed[::-1])
        compared_index = row_order[0]
        new_index_to_old = [[interm_to_orig_value_int[compared_index]]]
        for interm_index in row_order[1:]:
            if np.allclose(prob_matrix[compared_index], prob_matrix[interm_index]):
                new_index_to_old[-1].append(interm_to_orig_value_int[interm_index])
            else:
                compared_index = interm_index
                new_index_to_old.append([interm_to_orig_value_int[compared_index]])
        new_num_values = len(new_index_to_old)
        num_classes = interm_contingency_table.shape[1]
        new_contingency_table = np.zeros((new_num_values, num_classes), dtype=int)
        new_num_samples_per_value = np.zeros((new_num_values), dtype=int)
        for new_index, old_indices in enumerate(new_index_to_old):
            new_contingency_table[new_index] = np.sum(contingency_table[old_indices, :], axis=0)
            new_num_samples_per_value[new_index] = np.sum(values_num_samples[old_indices])
        return new_contingency_table, new_num_samples_per_value, new_index_to_old

    @staticmethod
    def _remove_empty_values(contingency_table, values_num_samples):
        # Define conversion from original values to new values
        orig_to_new_value_int = {}
        new_to_orig_value_int = []
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                orig_to_new_value_int[orig_value] = len(new_to_orig_value_int)
                new_to_orig_value_int.append(orig_value)

        # Generate the new contingency tables
        new_contingency_table = np.zeros((len(new_to_orig_value_int), contingency_table.shape[1]),
                                         dtype=int)
        new_value_num_seen = np.zeros((len(new_to_orig_value_int)), dtype=int)
        for orig_value, curr_num_samples in enumerate(values_num_samples):
            if curr_num_samples > 0:
                curr_new_value = orig_to_new_value_int[orig_value]
                new_value_num_seen[curr_new_value] = curr_num_samples
                np.copyto(dst=new_contingency_table[curr_new_value, :],
                          src=contingency_table[orig_value, :])

        return (new_to_orig_value_int,
                new_contingency_table,
                new_value_num_seen)

    @staticmethod
    def _change_split_to_use_old_values(new_left, new_right, new_index_to_old):
        """Change split values to use indices of original contingency table."""
        left_old_values = set()
        for new_index in new_left:
            left_old_values |= set(new_index_to_old[new_index])
        right_old_values = set()
        for new_index in new_right:
            right_old_values |= set(new_index_to_old[new_index])
        return left_old_values, right_old_values

    @classmethod
    def _get_principal_component(cls, num_samples, contingency_table, values_num_samples):
        """Returns the principal component of the weighted covariance matrix."""
        num_samples_per_class = cls._get_num_samples_per_class(contingency_table)
        avg_prob_per_class = np.divide(num_samples_per_class, num_samples)
        prob_matrix = contingency_table / values_num_samples[:, None]
        diff_prob_matrix = (prob_matrix - avg_prob_per_class).T
        weight_diff_prob = diff_prob_matrix * values_num_samples[None, :]
        weighted_squared_diff_prob_matrix = np.dot(weight_diff_prob, diff_prob_matrix.T)
        weighted_covariance_matrix = (1/(num_samples - 1)) * weighted_squared_diff_prob_matrix
        eigenvalues, eigenvectors = np.linalg.eigh(weighted_covariance_matrix)
        index_largest_eigenvalue = np.argmax(np.square(eigenvalues))
        return eigenvectors[:, index_largest_eigenvalue]

    @staticmethod
    def _get_num_samples_per_class(contingency_table):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_values, num_classes = contingency_table.shape
        num_samples_per_class = [0] * num_classes
        for value in range(num_values):
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[value, class_index]
        return num_samples_per_class



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                 HYPERCUBE COVER-ENTROPY                                   ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class HypercubeCoverEntropy(Criterion):
    """Hypercube Cover criterion using the Entropy impurity measure."""
    name = 'Hypercube Cover-Entropy'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the Hypercube Cover
        criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                best_entropy = float('+inf')
                best_left_values = set()
                best_right_values = set()
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                for (set_left_classes,
                     set_right_classes) in cls._generate_superclasses(
                         tree_node.class_index_num_samples):
                    (superclass_contingency_table,
                     superclass_index_num_samples) = cls._get_superclass_contingency_table(
                         tree_node.contingency_tables[attrib_index].contingency_table,
                         tree_node.contingency_tables[attrib_index].values_num_samples,
                         set_left_classes,
                         set_right_classes)
                    (curr_entropy,
                     left_values,
                     right_values) = cls._two_class_trick(
                         tree_node.class_index_num_samples,
                         superclass_index_num_samples,
                         values_seen,
                         tree_node.contingency_tables[attrib_index].contingency_table,
                         tree_node.contingency_tables[attrib_index].values_num_samples,
                         superclass_contingency_table,
                         len(tree_node.valid_samples_indices))

                    if curr_entropy < best_entropy:
                        best_entropy = curr_entropy
                        best_left_values = left_values
                        best_right_values = right_values
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[best_left_values, best_right_values],
                          criterion_value=best_entropy))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_entropy,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_entropy))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @classmethod
    def _get_information_gain_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                                    num_left_samples, num_right_samples):
        """Calculates the weighted Information Gain of a split."""
        num_samples = num_left_samples + num_right_samples
        left_entropy = cls._calculate_node_information(
            num_left_samples, num_samples_per_class_left)
        right_entropy = cls._calculate_node_information(
            num_right_samples, num_samples_per_class_right)
        split_information_gain = ((num_left_samples / num_samples) * left_entropy +
                                  (num_right_samples / num_samples) * right_entropy)
        return split_information_gain

    @classmethod
    def _calculate_node_information(cls, num_split_samples, num_samples_per_class_in_split):
        """Calculates the Information of the node given by the values."""
        information = 0.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            if curr_class_num_samples != 0:
                curr_frequency = curr_class_num_samples / num_split_samples
                information -= curr_frequency * math.log2(curr_frequency)
        return information

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @staticmethod
    def _generate_superclasses(class_index_num_samples):
        # We only need to look at superclasses of up to (len(class_index_num_samples)/2 + 1)
        # elements because of symmetry! The subsets we are not choosing are complements of the ones
        # chosen.
        non_empty_classes = set([])
        for class_index, class_num_samples in enumerate(class_index_num_samples):
            if class_num_samples > 0:
                non_empty_classes.add(class_index)
        number_non_empty_classes = len(non_empty_classes)

        for left_classes in itertools.chain.from_iterable(
                itertools.combinations(non_empty_classes, size_left_superclass)
                for size_left_superclass in range(1, number_non_empty_classes // 2 + 1)):
            set_left_classes = set(left_classes)
            set_right_classes = non_empty_classes - set_left_classes
            if not set_left_classes or not set_right_classes:
                # A valid split must have at least one sample in each side
                continue
            yield set_left_classes, set_right_classes

    @staticmethod
    def _get_superclass_contingency_table(contingency_table, values_num_samples, set_left_classes,
                                          set_right_classes):
        superclass_contingency_table = np.zeros((contingency_table.shape[0], 2), dtype=float)
        superclass_index_num_samples = [0, 0]
        for value, value_num_samples in enumerate(values_num_samples):
            if value_num_samples == 0:
                continue
            for class_index in set_left_classes:
                superclass_index_num_samples[0] += contingency_table[value][class_index]
                superclass_contingency_table[value][0] += contingency_table[value][class_index]
            for class_index in set_right_classes:
                superclass_index_num_samples[1] += contingency_table[value][class_index]
                superclass_contingency_table[value][1] += contingency_table[value][class_index]
        return superclass_contingency_table, superclass_index_num_samples

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_entropy = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                information_gain = cls._get_information_gain_value(class_num_left,
                                                                   class_num_right,
                                                                   num_left_samples,
                                                                   num_right_samples)
                if information_gain < best_entropy:
                    best_entropy = information_gain
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_entropy, best_last_left_value, best_first_right_value)

    @classmethod
    def _two_class_trick(cls, class_index_num_samples, superclass_index_num_samples, values_seen,
                         contingency_table, values_num_samples, superclass_contingency_table,
                         num_total_valid_samples):
        # TESTED!
        def _get_non_empty_superclass_indices(superclass_index_num_samples):
            # TESTED!
            first_non_empty_superclass = None
            second_non_empty_superclass = None
            for superclass_index, superclass_num_samples in enumerate(superclass_index_num_samples):
                if superclass_num_samples > 0:
                    if first_non_empty_superclass is None:
                        first_non_empty_superclass = superclass_index
                    else:
                        second_non_empty_superclass = superclass_index
                        break
            return first_non_empty_superclass, second_non_empty_superclass

        def _calculate_value_class_ratio(values_seen, values_num_samples,
                                         superclass_contingency_table, non_empty_class_indices):
            # TESTED!
            value_class_ratio = [] # [(value, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = superclass_contingency_table[
                    curr_value][second_class_index]
                value_class_ratio.append(
                    (curr_value, number_second_non_empty / values_num_samples[curr_value]))
            value_class_ratio.sort(key=lambda tup: tup[1])
            return value_class_ratio


        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_superclass,
         second_non_empty_superclass) = _get_non_empty_superclass_indices(
             superclass_index_num_samples)
        if first_non_empty_superclass is None or second_non_empty_superclass is None:
            return (float('+inf'), {0}, set())

        value_class_ratio = _calculate_value_class_ratio(values_seen,
                                                         values_num_samples,
                                                         superclass_contingency_table,
                                                         (first_non_empty_superclass,
                                                          second_non_empty_superclass))

        best_split_entropy = float('+inf')
        best_last_left_index = 0

        num_right_samples = num_total_valid_samples
        class_num_right = np.copy(class_index_num_samples)
        num_left_samples = 0
        class_num_left = np.zeros(class_num_right.shape, dtype=int)

        for last_left_index, (last_left_value, _) in enumerate(value_class_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            num_left_samples += num_samples_last_left_value
            num_right_samples -= num_samples_last_left_value
            class_num_left += contingency_table[last_left_value]
            class_num_right -= contingency_table[last_left_value]

            curr_information_gain = cls._get_information_gain_value(class_num_left,
                                                                    class_num_right,
                                                                    num_left_samples,
                                                                    num_right_samples)
            if curr_information_gain < best_split_entropy:
                best_split_entropy = curr_information_gain
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set(tup[0] for tup in value_class_ratio[:best_last_left_index + 1])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_entropy, set_left_values, set_right_values)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                               LARGEST CLASS ALONE-ENTROPY                                 ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class LargestClassAloneEntropy(Criterion):
    """Largest Class Alone criterion using the Entropy impurity measure."""
    name = 'Largest Class Alone-Entropy'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the Hypercube Cover
        criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                largest_class_index, _ = max(
                    enumerate(tree_node.class_index_num_samples), key=lambda x: x[1])
                (superclass_contingency_table,
                 superclass_index_num_samples) = cls._get_superclass_contingency_table(
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples,
                     tree_node.class_index_num_samples,
                     largest_class_index)
                (best_entropy,
                 left_values,
                 right_values) = cls._two_class_trick(
                     tree_node.class_index_num_samples,
                     superclass_index_num_samples,
                     values_seen,
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples,
                     superclass_contingency_table,
                     len(tree_node.valid_samples_indices))
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_values, right_values],
                          criterion_value=best_entropy))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_entropy,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_entropy))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @classmethod
    def _get_information_gain_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                                    num_left_samples, num_right_samples):
        """Calculates the weighted Information Gain of a split."""
        num_samples = num_left_samples + num_right_samples
        left_entropy = cls._calculate_node_information(
            num_left_samples, num_samples_per_class_left)
        right_entropy = cls._calculate_node_information(
            num_right_samples, num_samples_per_class_right)
        split_information_gain = ((num_left_samples / num_samples) * left_entropy +
                                  (num_right_samples / num_samples) * right_entropy)
        return split_information_gain

    @classmethod
    def _calculate_node_information(cls, num_split_samples, num_samples_per_class_in_split):
        """Calculates the Information of the node given by the values."""
        information = 0.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            if curr_class_num_samples != 0:
                curr_frequency = curr_class_num_samples / num_split_samples
                information -= curr_frequency * math.log2(curr_frequency)
        return information

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_superclass_contingency_table(contingency_table, values_num_samples,
                                          class_index_num_samples, largest_classes_index):
        superclass_contingency_table = np.array(
            [contingency_table[:, largest_classes_index],
             values_num_samples - contingency_table[:, largest_classes_index]
            ]).T
        superclass_index_num_samples = [
            class_index_num_samples[largest_classes_index],
            sum(class_index_num_samples) - class_index_num_samples[largest_classes_index]]
        return superclass_contingency_table, superclass_index_num_samples

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_entropy = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                information_gain = cls._get_information_gain_value(class_num_left,
                                                                   class_num_right,
                                                                   num_left_samples,
                                                                   num_right_samples)
                if information_gain < best_entropy:
                    best_entropy = information_gain
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_entropy, best_last_left_value, best_first_right_value)

    @classmethod
    def _two_class_trick(cls, class_index_num_samples, superclass_index_num_samples, values_seen,
                         contingency_table, values_num_samples, superclass_contingency_table,
                         num_total_valid_samples):
        # TESTED!
        def _get_non_empty_superclass_indices(superclass_index_num_samples):
            # TESTED!
            first_non_empty_superclass = None
            second_non_empty_superclass = None
            for superclass_index, superclass_num_samples in enumerate(superclass_index_num_samples):
                if superclass_num_samples > 0:
                    if first_non_empty_superclass is None:
                        first_non_empty_superclass = superclass_index
                    else:
                        second_non_empty_superclass = superclass_index
                        break
            return first_non_empty_superclass, second_non_empty_superclass

        def _calculate_value_class_ratio(values_seen, values_num_samples,
                                         superclass_contingency_table, non_empty_class_indices):
            # TESTED!
            value_class_ratio = [] # [(value, ratio_on_second_class)]
            second_class_index = non_empty_class_indices[1]
            for curr_value in values_seen:
                number_second_non_empty = superclass_contingency_table[
                    curr_value][second_class_index]
                value_class_ratio.append(
                    (curr_value, number_second_non_empty / values_num_samples[curr_value]))
            value_class_ratio.sort(key=lambda tup: tup[1])
            return value_class_ratio


        # We only need to sort values by the percentage of samples in second non-empty class with
        # this value. The best split will be given by choosing an index to split this list of
        # values in two.
        (first_non_empty_superclass,
         second_non_empty_superclass) = _get_non_empty_superclass_indices(
             superclass_index_num_samples)
        if first_non_empty_superclass is None or second_non_empty_superclass is None:
            return (float('+inf'), {0}, set())

        value_class_ratio = _calculate_value_class_ratio(values_seen,
                                                         values_num_samples,
                                                         superclass_contingency_table,
                                                         (first_non_empty_superclass,
                                                          second_non_empty_superclass))

        best_split_entropy = float('+inf')
        best_last_left_index = 0

        num_right_samples = num_total_valid_samples
        class_num_right = np.copy(class_index_num_samples)
        num_left_samples = 0
        class_num_left = np.zeros(class_num_right.shape, dtype=int)

        for last_left_index, (last_left_value, _) in enumerate(value_class_ratio[:-1]):
            num_samples_last_left_value = values_num_samples[last_left_value]
            # num_samples_last_left_value > 0 always, since the values without samples were not
            # added to the values_seen when created by cls._generate_value_to_index

            num_left_samples += num_samples_last_left_value
            num_right_samples -= num_samples_last_left_value
            class_num_left += contingency_table[last_left_value]
            class_num_right -= contingency_table[last_left_value]

            curr_information_gain = cls._get_information_gain_value(class_num_left,
                                                                    class_num_right,
                                                                    num_left_samples,
                                                                    num_right_samples)
            if curr_information_gain < best_split_entropy:
                best_split_entropy = curr_information_gain
                best_last_left_index = last_left_index

        # Let's get the values and split the indices corresponding to the best split found.
        set_left_values = set(tup[0] for tup in value_class_ratio[:best_last_left_index + 1])
        set_right_values = set(values_seen) - set_left_values

        return (best_split_entropy, set_left_values, set_right_values)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                       SLIQ-Ext                                            ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class SliqExt(Criterion):
    """SLIQ-Ext criterion using the Gini impurity measure."""
    name = 'SLIQ-ext'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the SLIQ-Ext criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                (best_gini,
                 left_values,
                 right_values) = cls._get_best_attribute_split(
                     values_seen,
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_values, right_values],
                          criterion_value=best_gini))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_gini,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_gini))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @classmethod
    def _calculate_split_gini_index(cls, contingency_table, values_num_samples, left_values,
                                    right_values):
        """Calculates the weighted Gini index of a split."""
        num_left_samples, num_right_samples = cls._get_num_samples_per_side(
            values_num_samples, left_values, right_values)
        num_samples_per_class_left = cls._get_num_samples_per_class_in_values(
            contingency_table, left_values)
        num_samples_per_class_right = cls._get_num_samples_per_class_in_values(
            contingency_table, right_values)
        return cls._get_gini_value(num_samples_per_class_left, num_samples_per_class_right,
                                   num_left_samples, num_right_samples)

    @classmethod
    def _get_gini_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                        num_left_samples, num_right_samples):
        """Calculates the weighted Gini index of a split."""
        num_samples = num_left_samples + num_right_samples
        left_gini = cls._calculate_node_gini_index(num_left_samples, num_samples_per_class_left)
        right_gini = cls._calculate_node_gini_index(num_right_samples, num_samples_per_class_right)
        return ((num_left_samples / num_samples) * left_gini +
                (num_right_samples / num_samples) * right_gini)

    @staticmethod
    def _calculate_node_gini_index(num_split_samples, num_samples_per_class_in_split):
        """Calculates the Gini index of a node."""
        if not num_split_samples:
            return 1.0
        gini_index = 1.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            gini_index -= (curr_class_num_samples / num_split_samples)**2
        return gini_index

    @staticmethod
    def _get_num_samples_per_side(values_num_samples, left_values, right_values):
        """Returns two sets, each containing the values of a split side."""
        num_left_samples = sum(values_num_samples[value] for value in left_values)
        num_right_samples = sum(values_num_samples[value] for value in right_values)
        return  num_left_samples, num_right_samples

    @staticmethod
    def _get_num_samples_per_class_in_values(contingency_table, values):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_classes = contingency_table.shape[1]
        num_samples_per_class = [0] * num_classes
        for value in values:
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[
                    value, class_index]
        return num_samples_per_class

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _get_best_attribute_split(cls, values_seen, contingency_table, num_samples_per_value):
        """Gets the attribute's best split according to the SLIQ-ext criterion."""
        best_gini = float('+inf')
        best_left_values = set()
        best_right_values = set()
        curr_left_values = set(values_seen)
        curr_right_values = set()
        while curr_left_values:
            iteration_best_gini = float('+inf')
            iteration_best_left_values = set()
            iteration_best_right_values = set()
            for value in curr_left_values:
                curr_left_values = curr_left_values - set([value])
                curr_right_values = curr_right_values | set([value])
                curr_gini = cls._calculate_split_gini_index(contingency_table,
                                                            num_samples_per_value,
                                                            curr_left_values,
                                                            curr_right_values)
                if curr_gini < iteration_best_gini:
                    iteration_best_gini = curr_gini
                    iteration_best_left_values = set(curr_left_values)
                    iteration_best_right_values = set(curr_right_values)
            if iteration_best_gini < best_gini:
                best_gini = iteration_best_gini
                best_left_values = set(iteration_best_left_values)
                best_right_values = set(iteration_best_right_values)
            curr_left_values = iteration_best_left_values
            curr_right_values = iteration_best_right_values
        return best_gini, best_left_values, best_right_values

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_gini = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                gini_value = cls._get_gini_value(class_num_left,
                                                 class_num_right,
                                                 num_left_samples,
                                                 num_right_samples)
                if gini_value < best_gini:
                    best_gini = gini_value
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_gini, best_last_left_value, best_first_right_value)



#################################################################################################
#################################################################################################
###                                                                                           ###
###                                    SLIQ-Ext-ENTROPY                                       ###
###                                                                                           ###
#################################################################################################
#################################################################################################

class SliqExtEntropy(Criterion):
    """SLIQ-Ext criterion using the Entropy impurity measure."""
    name = 'SLIQ-ext-Entropy'

    @classmethod
    def select_best_attribute_and_split(cls, tree_node):
        """Returns the best attribute and its best split, according to the SLIQ-Ext criterion.

        Args:
          tree_node (TreeNode): tree node where we want to find the best attribute/split.

        Returns the best split found.
        """
        best_splits_per_attrib = []
        for (attrib_index,
             (is_valid_nominal_attrib,
              is_valid_numeric_attrib)) in enumerate(zip(tree_node.valid_nominal_attribute,
                                                         tree_node.valid_numeric_attribute)):
            if is_valid_nominal_attrib:
                values_seen = cls._get_values_seen(
                    tree_node.contingency_tables[attrib_index].values_num_samples)
                (best_entropy,
                 left_values,
                 right_values) = cls._get_best_attribute_split(
                     values_seen,
                     tree_node.contingency_tables[attrib_index].contingency_table,
                     tree_node.contingency_tables[attrib_index].values_num_samples)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[left_values, right_values],
                          criterion_value=best_entropy))
            elif is_valid_numeric_attrib:
                values_and_classes = cls._get_numeric_values_seen(tree_node.valid_samples_indices,
                                                                  tree_node.dataset.samples,
                                                                  tree_node.dataset.sample_class,
                                                                  attrib_index)
                values_and_classes.sort()
                (best_entropy,
                 last_left_value,
                 first_right_value) = cls._solve_for_numeric(
                     values_and_classes,
                     tree_node.dataset.num_classes)
                best_splits_per_attrib.append(
                    Split(attrib_index=attrib_index,
                          splits_values=[{last_left_value}, {first_right_value}],
                          criterion_value=best_entropy))
        if best_splits_per_attrib:
            return min(best_splits_per_attrib, key=lambda split: split.criterion_value)
        return Split()

    @classmethod
    def _calculate_information_gain(cls, contingency_table, num_samples_per_value, left_values,
                                    right_values):
        """Calculates the Information Gain of the given binary split."""
        num_left_samples, num_right_samples = cls._get_num_samples_per_side(
            num_samples_per_value, left_values, right_values)
        num_samples_per_class_left = cls._get_num_samples_per_class_in_values(
            contingency_table, left_values)
        num_samples_per_class_right = cls._get_num_samples_per_class_in_values(
            contingency_table, right_values)
        return cls._get_information_gain_value(num_samples_per_class_left,
                                               num_samples_per_class_right,
                                               num_left_samples,
                                               num_right_samples)

    @classmethod
    def _get_information_gain_value(cls, num_samples_per_class_left, num_samples_per_class_right,
                                    num_left_samples, num_right_samples):
        """Calculates the weighted Information Gain of a split."""
        num_samples = num_left_samples + num_right_samples
        left_entropy = cls._calculate_node_information(
            num_left_samples, num_samples_per_class_left)
        right_entropy = cls._calculate_node_information(
            num_right_samples, num_samples_per_class_right)
        split_information_gain = ((num_left_samples / num_samples) * left_entropy +
                                  (num_right_samples / num_samples) * right_entropy)
        return split_information_gain

    @classmethod
    def _calculate_node_information(cls, num_split_samples, num_samples_per_class_in_split):
        """Calculates the Information of the node given by the values."""
        information = 0.0
        for curr_class_num_samples in num_samples_per_class_in_split:
            if curr_class_num_samples != 0:
                curr_frequency = curr_class_num_samples / num_split_samples
                information -= curr_frequency * math.log2(curr_frequency)
        return information

    @staticmethod
    def _get_num_samples_per_side(values_num_samples, left_values, right_values):
        """Returns two sets, each containing the values of a split side."""
        num_left_samples = sum(values_num_samples[value] for value in left_values)
        num_right_samples = sum(values_num_samples[value] for value in right_values)
        return  num_left_samples, num_right_samples

    @staticmethod
    def _get_num_samples_per_class_in_values(contingency_table, values):
        """Returns a list, i-th entry contains the number of samples of class i."""
        num_classes = contingency_table.shape[1]
        num_samples_per_class = [0] * num_classes
        for value in values:
            for class_index in range(num_classes):
                num_samples_per_class[class_index] += contingency_table[
                    value, class_index]
        return num_samples_per_class

    @staticmethod
    def _get_values_seen(values_num_samples):
        values_seen = set()
        for value, num_samples in enumerate(values_num_samples):
            if num_samples > 0:
                values_seen.add(value)
        return values_seen

    @staticmethod
    def _get_numeric_values_seen(valid_samples_indices, sample, sample_class, attrib_index):
        values_and_classes = []
        for sample_index in valid_samples_indices:
            sample_value = sample[sample_index][attrib_index]
            values_and_classes.append((sample_value, sample_class[sample_index]))
        return values_and_classes

    @classmethod
    def _get_best_attribute_split(cls, values_seen, contingency_table, num_samples_per_value):
        """Gets the attribute's best split according to the SLIQ-ext criterion."""
        best_entropy = float('+inf')
        best_left_values = set()
        best_right_values = set()
        curr_left_values = set(values_seen)
        curr_right_values = set()
        while curr_left_values:
            iteration_best_entropy = float('+inf')
            iteration_best_left_values = set()
            iteration_best_right_values = set()
            for value in curr_left_values:
                curr_left_values = curr_left_values - set([value])
                curr_right_values = curr_right_values | set([value])
                curr_entropy = cls._calculate_information_gain(contingency_table,
                                                               num_samples_per_value,
                                                               curr_left_values,
                                                               curr_right_values)
                if curr_entropy < iteration_best_entropy:
                    iteration_best_entropy = curr_entropy
                    iteration_best_left_values = set(curr_left_values)
                    iteration_best_right_values = set(curr_right_values)
            if iteration_best_entropy < best_entropy:
                best_entropy = iteration_best_entropy
                best_left_values = set(iteration_best_left_values)
                best_right_values = set(iteration_best_right_values)
            curr_left_values = iteration_best_left_values
            curr_right_values = iteration_best_right_values
        return best_entropy, best_left_values, best_right_values

    @classmethod
    def _solve_for_numeric(cls, sorted_values_and_classes, num_classes):
        last_left_value = sorted_values_and_classes[0][0]
        num_left_samples = 1
        num_right_samples = len(sorted_values_and_classes) - 1

        class_num_left = [0] * num_classes
        class_num_left[sorted_values_and_classes[0][1]] = 1

        class_num_right = [0] * num_classes
        for _, sample_class in sorted_values_and_classes[1:]:
            class_num_right[sample_class] += 1

        best_entropy = float('+inf')
        best_last_left_value = None
        best_first_right_value = None

        for first_right_index in range(1, len(sorted_values_and_classes)):
            first_right_value = sorted_values_and_classes[first_right_index][0]
            if first_right_value != last_left_value:
                information_gain = cls._get_information_gain_value(class_num_left,
                                                                   class_num_right,
                                                                   num_left_samples,
                                                                   num_right_samples)
                if information_gain < best_entropy:
                    best_entropy = information_gain
                    best_last_left_value = last_left_value
                    best_first_right_value = first_right_value

                last_left_value = first_right_value

            num_left_samples += 1
            num_right_samples -= 1
            first_right_class = sorted_values_and_classes[first_right_index][1]
            class_num_left[first_right_class] += 1
            class_num_right[first_right_class] -= 1
        return (best_entropy, best_last_left_value, best_first_right_value)
