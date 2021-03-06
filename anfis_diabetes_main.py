# -*- coding: utf-8 -*-
"""ANFIS_Diabetes_main.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1--_Z8YO2MjBmIPKDjfrCZpL4apZD9ewq
"""

from google.colab import drive
drive.mount('/content/gdrive')

import numpy as np
import itertools

def f_activation(z):
    """
    Numerically stable version of the sigmoid function (reference:
    http://fa.bianp.net/blog/2019/evaluate_logistic/#sec3.)
    """
    a = np.zeros_like(z)

    idx = (z >= 0.0)
    a[idx] = 1.0 / (1.0 + np.exp(-z[idx]))

    idx = np.invert(idx)                # Same as idx = (z < 0.0)
    a[idx] = np.exp(z[idx]) / (1.0 + np.exp(z[idx]))

    return a


def logsig(z):
    """
    Numerically stable version of the log-sigmoid function (reference:
    http://fa.bianp.net/blog/2019/evaluate_logistic/#sec3.)
    """
    a = np.zeros_like(z)

    idx = (z < -33.3)
    a[idx] = z[idx]

    idx = (z >= -33.3) & (z < -18.0)
    a[idx] = z[idx] - np.exp(z[idx])

    idx = (z >= -18.0) & (z < 37.0)
    a[idx] = - np.log1p(np.exp(-z[idx]))

    idx = (z >= 37.0)
    a[idx] = - np.exp(-z[idx])

    return a


def build_class_matrix(Y):
    """
    Builds the output array <Yout> for a classification problem. Array <Y> has
    dimensions (n_samples, 1) and <Yout> has dimension (n_samples, n_classes).
    Yout[i,j] = 1 specifies that the i-th sample belongs to the j-th class.
    """
    n_samples = Y.shape[0]

    # Classes and corresponding number
    Yu, idx = np.unique(Y, return_inverse=True)
    n_classes = len(Yu)

    # Build the array actually used for classification
    Yout = np.zeros((n_samples, n_classes))
    Yout[np.arange(n_samples), idx] = 1.0

    return Yout, Yu


class ANFIS:

    def __init__(self, n_mf, n_outputs, problem=None):
        """
        n_mf        (n_inputs, )        Number of MFs in each feature/input
        n_outputs                       Number of labels/classes
        problem     C = classification problem, otherwise continuous problem
        """
        self.n_mf = np.asarray(n_mf)
        self.n_outputs = n_outputs
        self.problem = problem

        self.n_inputs = len(n_mf)               # Number of features/inputs
        self.n_pf = self.n_mf.sum()             # Number of premise MFs
        self.n_cf = self.n_mf.prod()            # Number of consequent MFs

        # Number of variables
        self.n_var = 3 * self.n_pf \
                     + (self.n_inputs + 1) * self.n_cf * self.n_outputs

        self.init_prob = True                   # Initialization flag
        self.Xe = np.array([])                  # Extended input array

        # For logistic regression only
        if (self.problem == 'C'):
            self.Yout = np.array([])            # Actual output
            self.Yu = np.array([])              # Class list

    def create_model(self, theta, args):
        """
        Creates the model for the regression problem.
        """
        # Unpack
        X = args[0]                 # Input dataset
        Y = args[1]                 # Output dataset

        # First time only
        if (self.init_prob):
            self.init_prob = False

            # Build all combinations of premise MFs
            self.build_combs()

            # Expand the input dataset to match the number of premise MFs.
            self.Xe = self.expand_input_dataset(X)

            # For classification initialize Yout (output) and Yu (class list)
            if (self.problem == 'C'):
                self.Yout, self.Yu = build_class_matrix(Y)

        # Builds the premise/consequent parameters mu, s, c, and A
        self.build_param(theta)

        # Calculate the output
        f = self.forward_steps(X, self.Xe)

        # Cost function for classification problems (the activation value is
        # calculated in the logsig function)
        if (self.problem == 'C'):
            error = (1.0 - self.Yout) * f - logsig(f)
            J = error.sum() / float(X.shape[0])

        # Cost function for continuous problems
        else:
            error = f - Y
            J = (error ** 2).sum() / 2.0

        return J

    def eval_data(self, Xp):
        """
        Evaluates the input dataset with the model created in <create_model>.
        """
        # Expand the input dataset to match the number of premise MFs.
        Xpe = self.expand_input_dataset(Xp)

        # Calculate the output
        f = self.forward_steps(Xp, Xpe)

        # Classification problem
        if (self.problem == 'C'):
            A = f_activation(f)
            idx = np.argmax(A, axis=1)
            Yp = self.Yu[idx].reshape((len(idx), 1))

        # Continuous problem
        else:
            Yp = f

        return Yp

    def build_combs(self):
        """
        Builds all combinations of premise functions.
        For example if <n_mf> = [3, 2], the MF indexes for the first feature
        would be [0, 1, 2] and for the second feature would be [3, 4]. The
        resulting combinations would be <combs> = [[0 0 1 1 2 2],
                                                   [3 4 3 4 3 4]].
        """
        idx = np.cumsum(self.n_mf)
        v = [np.arange(0, idx[0])]

        for i in range(1, self.n_inputs):
            v.append(np.arange(idx[i-1], idx[i]))

        list_combs = list(itertools.product(*v))
        self.combs = np.asarray(list_combs).T

    def expand_input_dataset(self, X):
        """
        Expands the input dataset to match the number of premise MFs. Each MF
        will be paired with the correct feature in the dataset.
        """
        n_samples = X.shape[0]
        Xe = np.zeros((n_samples, self.n_pf))       # Expanded array
        idx = np.cumsum(self.n_mf)
        i1 = 0

        for i in range(self.n_inputs):
            i2 = idx[i]
            Xe[:, i1:i2] = X[:, i].reshape(n_samples, 1)
            i1 = idx[i]

        return Xe

    def build_param(self, theta):
        """
        Builds the premise/consequent parameters  mu, s, c, and A.
        """
        i1 = self.n_pf
        i2 = 2 * i1
        i3 = 3 * i1
        i4 = self.n_var

        # Premise function parameters (generalized Bell functions)
        self.mu = theta[0:i1]
        self.s = theta[i1:i2]
        self.c = theta[i2:i3]

        # Consequent function parameters (hyperplanes)
        self.A = \
            theta[i3:i4].reshape(self.n_inputs + 1, self.n_cf * self.n_outputs)

    def forward_steps(self, X, Xe):
        """
        Calculate the output giving premise/consequent parameters and the
        input dataset.
        """
        n_samples = X.shape[0]

        # Layer 1: premise functions (pf)
        d = (Xe - self.mu) / self.s
        pf = 1.0 / (1.0 + (d * d) ** self.c)

        # Layer 2: firing strenght (W)
        W = np.prod(pf[:, self.combs], axis=1)

        # Layer 3: firing strenght ratios (Wr)
        Wr = W / W.sum(axis=1, keepdims=True)

        # Layer 4and 5: consequent functions (cf) and output (f)
        X1 = np.hstack((np.ones((n_samples, 1)), X))
        f = np.zeros((n_samples, self.n_outputs))
        for i in range(self.n_outputs):
            i1 = i * self.n_cf
            i2 = (i + 1) * self.n_cf
            cf = Wr * (X1 @ self.A[:, i1:i2])
            f[:, i] = cf.sum(axis=1)

        return f

    def param_anfis(self):
        """
        Returns the premise MFs parameters.
        """
        mu = self.mu
        s = self.s
        c = self.c
        A = self.A

        return mu, s, c, A

import numpy as np
import matplotlib.pyplot as plt


def normalize_data(X, param=(), ddof=0):
    """
    If mu and sigma are not defined, returns a column-normalized version of
    X with zero mean and standard deviation equal to one. If mu and sigma are
    defined returns a column-normalized version of X using mu and sigma.
    X           Input dataset
    Xn          Column-normalized input dataset
    param       Tuple with mu and sigma
    mu          Mean
    sigma       Standard deviation
    ddof        Delta degrees of freedom (if ddof = 0 then divide by m, if
                ddof = 1 then divide by m-1, with m the number of data in X)
    """
    # Column-normalize using mu and sigma
    if (len(param) > 0):
        Xn = (X - param[0]) / param[1]
        return Xn

    # Column-normalize using mu=0 and sigma=1
    else:
        mu = X.mean(axis=0)
        sigma = X.std(axis=0, ddof=ddof)
        Xn = (X - mu) / sigma
        param = (mu, sigma)
        return Xn, param


def scale_data(X, param=()):
    """
    If X_min and X_max are not defined, returns a column-scaled version of
    X in the interval (-1,+1). If X_min and X_max are defined returns a
    column-scaled version of X using X_min and X_max.
    X           Input dataset
    Xs          Column-scaled input dataset
    param       Tuple with X_min and X_max
    X_min       Min. value along the columns (features) of the input dataset
    X_max       Max. value along the columns (features) of the input dataset
    """
    # Column-scale using X_min and X_max
    if (len(param) > 0):
        Xs = -1.0 + 2.0 * (X - param[0]) / (param[1] - param[0])
        return Xs

    # Column-scale using X_min=-1 and X_max=+1
    else:
        X_min = np.amin(X, axis=0)
        X_max = np.amax(X, axis=0)
        Xs = -1.0 + 2.0 * (X - X_min) / (X_max - X_min)
        param = (X_min, X_max)
        return Xs, param


def get_classes(Y):
    """
    Returns the number of classes (unique values) in array Y and the
    corresponding list.
    """
    class_list = np.unique(Y)
    n_classes = len(class_list)

    return n_classes, class_list


def build_classes(Y):
    """
    Builds the output array Yout for a classification problem. Array Y has
    dimensions (n_data, ) while Yout has dimension (n_data, n_classes).
    Yout[i,j] = 1 specifies that the i-th input belongs to the j-th class.
    Y can be an array of integer or an array of strings.
    """
    n_data = Y.shape[0]

    # Classes and corresponding number
    Yu, idx = np.unique(Y, return_inverse=True)
    n_classes = len(Yu)

    # Build the output array actually used for classification
    Yout = np.zeros((n_data, n_classes))
    Yout[np.arange(n_data), idx] = 1.0

    return Yout, Yu


def regression_sol(X, Y):
    """
    Returns the closed-form solution to the continuous regression problem.
    X           (m, 1+N)        Input dataset (must include column of 1s)
    Y           (m, k)          Output dataset
    theta       (1+N, k)        Regression parameters
    m = number of data in the input dataset
    N = number of features in the (original) input dataset
    k = number of labels in the output dataset
    p = number of parameters equal to (1+N) x k
    Note: each COLUMN contains the coefficients for each output/label.
    """
    theta = np.linalg.pinv(X.T @ X) @ X.T @ Y

    return theta


def calc_rmse(a, b):
    """
    Calculates the root-mean-square-error of arrays <a> and <b>. If the arrays
    are multi-column, the RMSE is calculated as all the columns are one single
    vector.
    """
    # Convert to (n, ) dimension
    a = a.flatten()
    b = b.flatten()

    # Root-mean-square-error
    rmse = np.sqrt(((a - b) ** 2).sum() / len(a))

    return rmse


def calc_corr(a, b):
    """
    Calculates the correlation between arrays <a> and <b>. If the arrays are
    multi-column, the correlation is calculated as all the columns are one
    single vector.
    """
    # Convert to (n, ) dimension
    a = a.flatten()
    b = b.flatten()

    # Correlation
    corr = np.corrcoef(a, b)[0, 1]

    return corr


def calc_accu(a, b):
    """
    Calculates the accuracy (in %) between arrays <a> and <b>. The two arrays
    must be column/row vectors.
    """
    # Convert to (n, ) dimension
    a = a.flatten()
    b = b.flatten()

    # Correlation
    accu = 100.0 * (a == b).sum() / len(a)

    return accu


def info_anfis(n_mf, n_outputs):
    """
    Returns number of premise functions <n_pf>, number of consequent functions
    <n_cf>, and number of variables <n_var> for the ANFIS defined by <n_mf>
    and <n_outputs>.
    """
    n_mf = np.asarray(n_mf)

    n_pf = n_mf.sum()
    n_cf = n_mf.prod()
    n_var = 3 * n_pf + (len(n_mf) + 1) * n_cf * n_outputs

    return n_pf, n_cf, n_var


def plot_mfs(n_mf, mu, s, c, X):
    """
    Plot the generalized Bell functions defined by mu, c, and s.
    X           (n_samples, n_inputs)       Input dataset
    n_mf        (n_inputs, )                Number of MFs in each feature/input
    mu          (n_pf, )                    Mean
    s           (n_pf, )                    Standard deviation
    c           (n_pf, )                    Exponent
    n_samples           Number of samples
    n_inputs            Number of features/inputs
    n_pf                Number of premise MFs
    """
    const = 0.1                 # Plot all values from <const> to 1
    idx = np.cumsum(n_mf)
    i1 = 0

    # Loop over all features/inputs
    for j in range(len(n_mf)):

        i2 = idx[j]
        names = []

        # Loop over all MFs in the same feature/input
        for i in range(i1, i2):

            # Point where the MF is equal to <const> (wrt the mean mu)
            t_delta = s[i] * ((1.0 - const) / const) ** (1.0 / (2.0 * c[i]))
            t = np.linspace(mu[i]-t_delta, mu[i]+t_delta, num=200)

            # MF values
            d = (t - mu[i]) / s[i]
            pf = 1.0 / (1.0 + ((d ** 2.0) ** c[i]))

            names.append(str(i+1))      # Feature/input number
            plt.plot(t, pf)

        # Min. and max. values in the feature/input
        X_min = np.amin(X[:, j])
        X_max = np.amax(X[:, j])

        # Draw vertical lines to show the dataset range for the feature/input
        plt.axvline(X_min, lw=1.5, ls='--', C='k')
        plt.axvline(X_max, lw=1.5, ls='--', C='k')

        # Format and show all MFs for this feature/input
        plt.grid(b=True)
        plt.title('Feature nr. ' + str(j+1))
        plt.xlabel('$X_' + str(j+1) + '$')
        plt.ylabel('$MF$')
        plt.ylim(0, 1)
        plt.legend(names)
        plt.show()

        # Next feature/input
        i1 = idx[j]


def bounds_pso(X, n_mf, n_outputs, mu_delta=0.2, s_par=[0.5, 0.2],
               c_par=[1.0, 3.0], A_par=[-10.0, 10.0]):
    """
    Builds the boundaries for the PSO using a few simple heuristic rules.
    Premise parameters:
    - Means (mu) are equidistributed (starting from the min. value) along the
      input dataset and are allowed to move by <mu_delta> on each side. The
      value of <mu_delta> is expressed as fraction of the range.
    - Standard deviations (s) are initially the same for all MFs, and are given
      using a middle value <s_par[0]> and its left/right variation <s_par[1]>.
      The middle value is scaled based on the actual range of inputs.
    - Exponents (c) are initially the same for all MFs, and are given using a
      range, i.e. a min. value <c_par[0]> and a max. value <c_par[1]>.
    Consequent parameters:
    - Coefficients (A) are given using a range, i.e. a min. value <A_par[0]>
      and a max. value <A_par[1]>.
    """
    n_inputs = len(n_mf)
    n_pf, n_cf, n_var = info_anfis(n_mf, n_outputs)

    i1 = n_pf
    i2 = 2 * i1
    i3 = 3 * i1
    i4 = n_var

    LB = np.zeros(n_var)
    UB = np.zeros(n_var)

    # Premise parameters (mu, s, c)
    idx = 0
    for i in range(n_inputs):

        # Feature/input min, max, and range
        X_min = np.amin(X[:, i])
        X_max = np.amax(X[:, i])
        X_delta = X_max - X_min

        # If there is only one MF
        if (n_mf[i] == 1):
            X_step = 0.0
            X_start = (X_min + X_max) / 2.0
            s = s_par[0]

        # If there is more than one MF
        else:
            X_step = X_delta / float(n_mf[i] - 1)
            X_start = X_min
            s = s_par[0] * X_step

        # Assign values to boundary arrays LB and UB
        for j in range(n_mf[i]):
            mu = X_start + X_step * float(j)
            LB[idx] = mu - mu_delta * X_delta           # mu lower limit
            UB[idx] = mu + mu_delta * X_delta           # mu upper limit
            LB[i1+idx] = s - s_par[1]                   # s lower limit
            UB[i1+idx] = s + s_par[1]                   # s upper limit
            LB[i2+idx] = c_par[0]                       # c lower limit
            UB[i2+idx] = c_par[1]                       # c upper limit
            idx += 1

    # Consequent parameters (A)
    LB[i3:i4] = A_par[0]                # A lower limit
    UB[i3:i4] = A_par[1]                # A upper limit

    return LB, UB

def PSO(func, LB, UB, nPop=40, epochs=500, K=0, phi=2.05, vel_fact=0.5,
        conf_type='RB', IntVar=None, normalize=False, rad=0.1, args=None):
    """
    func            Function to minimize
    LB              Lower boundaries of the search space
    UB              Upper boundaries of the search space
    nPop            Number of agents (population)
    epochs          Number of iterations
    K               Average size of each agent's group of informants
    phi             Coefficient to calculate the two confidence coefficients
    vel_fact        Velocity factor to calculate the maximum and the minimum
                    allowed velocities
    conf_type       Confinement type (on the velocities)
    IntVar          List of indexes specifying which variable should be treated
                    as integers
    normalize       Specifies if the search space should be normalized (to
                    improve convergency)
    rad             Normalized radius of the hypersphere centered on the best
                    particle.
    args            Tuple containing any parameter that needs to be passed to
                    the function
    Dimensions:
    (nVar, )        LB, UB, LB_orig, UB_orig, vel_max, vel_min, swarm_best_pos
    (nPop, nVar)    agent_pos, agent_vel, agent_best_pos, Gr, group_best_pos,
                    agent_pos_orig, agent_pos_tmp, vel_conf, out, x_sphere, u
    (nPop, nPop)    informants, informants_cost
    (nPop)          agent_best_cost, agent_cost, p_equal_g, better, r_max, r,
                    norm
    (0-nVar, )      IntVar
    """
    # Dimension of the search space and max. allowed velocities
    nVar = len(LB)
    vel_max = vel_fact * (UB - LB)
    vel_min = - vel_max

    # Confidence coefficients
    w = 1.0 / (phi - 1.0 + np.sqrt(phi**2 - 2.0 * phi))
    cmax = w * phi

    # Probability an agent is an informant
    p_informant = 1.0 - (1.0 - 1.0 / float(nPop)) ** K

    # Normalize search space if requested
    if (normalize):
        LB_orig = LB.copy()
        UB_orig = UB.copy()
        LB = np.zeros(nVar)
        UB = np.ones(nVar)

    # Define (if any) which variables are treated as integers (indexes are in
    # the range 1 to nVar)
    if (IntVar is None):
        nIntVar = 0
    elif (IntVar == 'all'):
        IntVar = np.arange(nVar, dtype=int)
        nIntVar = nVar
    else:
        IntVar = np.asarray(IntVar, dtype=int) - 1
        nIntVar = len(IntVar)

    # Initial position of each agent
    agent_pos = LB + np.random.rand(nPop, nVar) * (UB - LB)
    if (nIntVar > 0):
        agent_pos[:, IntVar] = np.round(agent_pos[:, IntVar])

    # Initial velocity of each agent (with velocity limits)
    agent_vel = (LB - agent_pos) + np.random.rand(nPop, nVar) * (UB - LB)
    agent_vel = np.fmin(np.fmax(agent_vel, vel_min), vel_max)

    # Initial cost of each agent
    if (normalize):
        agent_pos_orig = LB_orig + agent_pos * (UB_orig - LB_orig)
        agent_cost = func(agent_pos_orig, args)
    else:
        agent_cost = func(agent_pos, args)

    # Initial best position/cost of each agent
    agent_best_pos = agent_pos.copy()
    agent_best_cost = agent_cost.copy()

    # Initial best position/cost of the swarm
    idx = np.argmin(agent_best_cost)
    swarm_best_pos = agent_best_pos[idx, :]
    swarm_best_cost = agent_best_cost[idx]
    swarm_best_idx = idx

    # Initial best position of each agent using the swarm
    if (K == 0):
        group_best_pos = np.tile(swarm_best_pos, (nPop, 1))
        p_equal_g = \
            (np.where(np.arange(nPop) == idx, 0.75, 1.0)).reshape(nPop, 1)

    # Initial best position of each agent using informants
    else:
        informants = np.where(np.random.rand(nPop, nPop) < p_informant, 1, 0)
        np.fill_diagonal(informants, 1)
        group_best_pos, p_equal_g = group_best(informants, agent_best_pos,
                                               agent_best_cost)

    # Main loop
    for epoch in range(epochs):

        # Determine the updated velocity for each agent
        Gr = agent_pos + (1.0 / 3.0) * cmax * \
             (agent_best_pos + group_best_pos - 2.0 * agent_pos) * p_equal_g
        x_sphere = hypersphere_point(Gr, agent_pos)
        agent_vel = w * agent_vel + Gr + x_sphere - agent_pos

        # Impose velocity limits
        agent_vel = np.fmin(np.fmax(agent_vel, vel_min), vel_max)

        # Temporarly update the position of each agent to check if it is
        # outside the search space
        agent_pos_tmp = agent_pos + agent_vel
        if (nIntVar > 0):
            agent_pos_tmp[:, IntVar] = np.round(agent_pos_tmp[:, IntVar])
        out = np.logical_not((agent_pos_tmp > LB) * (agent_pos_tmp < UB))

        # Apply velocity confinement rules
        if (conf_type == 'RB'):
            vel_conf = random_back_conf(agent_vel)

        elif (conf_type == 'HY'):
            vel_conf = hyperbolic_conf(agent_pos, agent_vel, UB, LB)

        elif (conf_type == 'MX'):
            vel_conf = mixed_conf(agent_pos, agent_vel, UB, LB)

        # Update velocity and position of each agent (all <vel_conf> velocities
        # are smaller than the max. allowed velocity)
        agent_vel = np.where(out, vel_conf, agent_vel)
        agent_pos += agent_vel
        if (nIntVar > 0):
            agent_pos[:, IntVar] = np.round(agent_pos[:, IntVar])

        # Apply position confinement rules to agents outside the search space
        agent_pos = np.fmin(np.fmax(agent_pos, LB), UB)
        if (nIntVar > 0):
            agent_pos[:, IntVar] = np.fmax(agent_pos[:, IntVar],
                                           np.ceil(LB[IntVar]))
            agent_pos[:, IntVar] = np.fmin(agent_pos[:, IntVar],
                                           np.floor(UB[IntVar]))

        # Calculate new cost of each agent
        if (normalize):
            agent_pos_orig = LB_orig + agent_pos * (UB_orig - LB_orig)
            agent_cost = func(agent_pos_orig, args)
        else:
            agent_cost = func(agent_pos, args)

        # Update best position/cost of each agent
        better = (agent_cost < agent_best_cost)
        agent_best_pos[better, :] = agent_pos[better, :]
        agent_best_cost[better] = agent_cost[better]

        # Update best position/cost of the swarm
        idx = np.argmin(agent_best_cost)
        if (agent_best_cost[idx] < swarm_best_cost):
            swarm_best_pos = agent_best_pos[idx, :]
            swarm_best_cost = agent_best_cost[idx]
            swarm_best_idx = idx

        # If the best cost of the swarm did not improve ....
        else:
            # .... when using swarm -> do nothing
            if (K == 0):
                pass

            # .... when using informants -> change informant groups
            else:
                informants = \
                    np.where(np.random.rand(nPop, nPop) < p_informant, 1, 0)
                np.fill_diagonal(informants, 1)

        # Update best position of each agent using the swarm
        if (K == 0):
            group_best_pos = np.tile(swarm_best_pos, (nPop, 1))

        # Update best position of each agent using informants
        else:
            group_best_pos, p_equal_g, = group_best(informants, agent_best_pos,
                                                    agent_best_cost)

    # If necessary de-normalize and determine the (normalized) distance between
    # the best particle and all the others
    if (normalize):
        delta = agent_best_pos - swarm_best_pos         # (UB-LB = 1)
        swarm_best_pos = LB_orig + swarm_best_pos * (UB_orig - LB_orig)
    else:
        deltaB = np.fmax(UB-LB, 1.e-10)             # To avoid /0 when LB = UB
        delta = (agent_best_pos - swarm_best_pos) / deltaB

    # Number of particles in the hypersphere of radius <rad> around the best
    # particle
    dist = np.linalg.norm(delta/np.sqrt(nPop), axis=1)
    in_rad = (dist < rad).sum()

    # Return info about the solution
    info = (swarm_best_cost, swarm_best_idx, in_rad)

    return swarm_best_pos, info


def group_best(informants, agent_best_pos, agent_best_cost):
    """
    Determine the group best position of each agent based on the agent
    informants.
    """
    nPop, nVar = agent_best_pos.shape

    # Determine the cost of each agent in each group (set to infinity the value
    # for agents that are not informants of the group)
    informants_cost = np.where(informants == 1, agent_best_cost, np.inf)

    # For each agent determine the agent with the best cost in the group and
    # assign its position to it
    idx = np.argmin(informants_cost, axis=1)
    group_best_pos = agent_best_pos[idx, :]

    # Build the vector to correct the velocity update for the corner case where
    # the agent is also the group best
    p_equal_g = (np.where(np.arange(nPop) == idx, 0.75, 1.0)).reshape(nPop, 1)

    return group_best_pos, p_equal_g


def hypersphere_point(Gr, agent_pos):
    """
    For each agent determine a random point inside the hypersphere (Gr,|Gr-X|),
    where Gr is its center, |Gr-X| is its radius, and X is the agent position.
    """
    nPop, nVar = agent_pos.shape

    # Hypersphere radius of each agent
    r_max = np.linalg.norm(Gr - agent_pos, axis=1)

    # Randomly pick a direction using a normal distribution and a radius
    # (inside the hypersphere)
    u = np.random.normal(0.0, 1.0, (nPop, nVar))
    norm = np.linalg.norm(u, axis=1)
    r = np.random.uniform(0.0, r_max, nPop)

    # Coordinates of the point with direction <u> and at distance <r> from the
    # hypersphere center
    x_sphere = u * (r / norm).reshape(nPop, 1)

    return x_sphere


def hyperbolic_conf(agent_pos, agent_vel, UB, LB):
    """
    Apply hyperbolic confinement to agent velocities (calculation is done on
    all agents to avoid loops but the change will be applied only to the agents
    actually outside the search space).
    """
    # If the update velocity is > 0
    if_pos_vel = agent_vel / (1.0 + np.abs(agent_vel / (UB - agent_pos)))

    # If the update velocity is <= 0
    if_neg_vel = agent_vel / (1.0 + np.abs(agent_vel / (agent_pos - LB)))

    # Confinement velocity
    vel_conf = np.where(agent_vel > 0, if_pos_vel, if_neg_vel)

    return vel_conf


def random_back_conf(agent_vel):
    """
    Apply random-back confinement to agent velocities (calculation is done on
    all agents to avoid loops but the change will be applied only to the agents
    actually outside the search space).
    """
    nPop, nVar = agent_vel.shape

    # Confinement velocity
    vel_conf = - np.random.rand(nPop, nVar) * agent_vel

    return vel_conf


def mixed_conf(agent_pos, agent_vel, UB, LB):
    """
    Apply a mixed-type confinement to agent velocities (calculation is done on
    all agents to avoid loops but the change will be applied only to the agents
    actually outside the search space).
    For each agent the confinement type (hyperbolic or random-back) is choosen
    randomly.
    """
    nPop, nVar = agent_pos.shape

    # Hyperbolic confinement
    vel_conf_HY = hyperbolic_conf(agent_pos, agent_vel, UB, LB)

    # random-back confinement
    vel_conf_RB = random_back_conf(agent_vel)

    # Confinement velocity
    gamma = np.random.rand(nPop, nVar)
    vel_conf = np.where(gamma >= 0.5, vel_conf_HY, vel_conf_RB)

    return vel_conf

# Default values common to all examples
problem = None
split_factor = 0.75
K = 10 #Average size of each agent's group of informants
phi = 2.05
vel_fact = 0.5
conf_type = 'RB'
IntVar = None
normalize = False
rad = 0.1
mu_delta = 0.1
s_par = [0.5, 0.2]
c_par = [1.0, 3.0]
A_par = [-10.0, 10.0]

# Dataset: 2 features (inputs), 6 classes (outputs), 1599 samples
# ANFIS: layout of [3, 2], 123 variables
# Predicted/actual accuracy values: 58.2% (training), 59.8% (test).
# https://archive.ics.uci.edu/ml/datasets/Wine+Quality
data_file = '/content/gdrive/MyDrive/??o???? a??n 2 - 27 02/dataclean.csv'
# data_file = '/content/gdrive/MyDrive/??o???? a??n 2 - 27 02/PCA_3dim.csv'
problem = 'C'
n_mf = [2,2,2,2,2,2]
nPop = 40
epochs = 500

import pandas as pd

data = pd.read_csv(data_file).values
n_samples, n_cols = data.shape
n_samples, n_cols
data

if (problem == 'C'):
    n_inputs = n_cols - 1
    n_outputs, class_list = get_classes(data[:, -1])
n_outputs, class_list

"""Split data"""

# ANFIS info
n_pf, n_cf, n_var = info_anfis(n_mf, n_outputs)
# Randomly build the training (tr) and test (te) datasets
# rows_tr = int(split_factor * n_samples)
# rows_te = n_samples - rows_tr
# idx_tr = np.random.choice(np.arange(n_samples), size=rows_tr, replace=False)
# idx_te = np.delete(np.arange(n_samples), idx_tr)
# data_tr = data[idx_tr, :]
# data_te = data[idx_te, :]

# # Split the data
# X_tr = data_tr[:, 0:n_inputs]
# Y_tr = data_tr[:, n_inputs:]
# X_te = data_te[:, 0:n_inputs]
# Y_te = data_te[:, n_inputs:]

from sklearn.model_selection import train_test_split
from sklearn.tree import  DecisionTreeClassifier

X_tr, X_te, Y_tr, Y_te = train_test_split(data[:, 0:n_inputs], data[:, n_inputs:], test_size = 0.25)
rows_tr = X_tr.shape[0]
rows_te = X_te.shape[0]

# System info
print("\nNumber of samples = ", n_samples)
print("Number of inputs = ", n_inputs)
print("Number of outputs = ", n_outputs)

if (problem == 'C'):
    print("\nClasses: ", class_list)

print("\nNumber of training samples = ", rows_tr)
print("Number of test samples= ", rows_te)

print("\nANFIS layout = ", n_mf)
print("Number of premise functions = ", n_pf)
print("Number of consequent functions = ", n_cf)
print("Number of variables = ", n_var)

# ======= PSO ======= #


def interface_PSO(theta, args):
    """
    Function to interface the PSO with the ANFIS. Each particle has its own
    ANFIS instance.
    theta           (nPop, n_var)
    learners        (nPop, )
    J               (nPop, )
    """
    args_PSO = (args[0], args[1])
    learners = args[2]
    nPop = theta.shape[0]

    J = np.zeros(nPop)
    for i in range(nPop):
        J[i] = learners[i].create_model(theta[i, :], args_PSO)

    return J

# Init learners (one for each particle)
learners = []
for i in range(nPop):
    learners.append(ANFIS(n_mf=n_mf, n_outputs=n_outputs, problem=problem))

# Always normalize inputs
Xn_tr, norm_param = normalize_data(X_tr)
Xn_te = normalize_data(X_te, norm_param)

# Build boundaries using heuristic rules
LB, UB = bounds_pso(Xn_tr, n_mf, n_outputs, mu_delta=mu_delta, s_par=s_par,
                        c_par=c_par, A_par=A_par)

# Scale output(s) in continuous problems to reduce the range in <A_par>
if (problem != 'C'):
    Y_tr, scal_param = scale_data(Y_tr)
    Y_te = scale_data(Y_te, scal_param)

# Optimize using PSO
# theta = best solution (min)
# info[0] = function value in theta
# info[1] = index of the learner with the best solution
# info[2] = number of learners close to the learner with the best solution
func = interface_PSO
args = (Xn_tr, Y_tr, learners)
theta, info = PSO(func, LB, UB, nPop=nPop, epochs=epochs, K=K, phi=phi,
                      vel_fact=vel_fact, conf_type=conf_type, IntVar=IntVar,
                      normalize=normalize, rad=rad, args=args)

# ======= Solution ======= #

best_learner = learners[info[1]]
mu, s, c, A = best_learner.param_anfis()

# print("\nSolution:")
# print("J minimum = ", info[0])
# print("Best learner = ", info[1])
# print("Close learners = ", info[2])

# print("\nCoefficients:")
# print("mu = ", mu)
# print("s  = ", s)
# print("c  = ", c)
# print("A =")
# print(A)

# Plot resulting MFs
plot_mfs(n_mf, mu, s, c, Xn_tr)


# Evaluate training and test datasets with best learner
# (in continuous problems these are already scaled values)
Yp_tr = best_learner.eval_data(Xn_tr)
Yp_te = best_learner.eval_data(Xn_te)

from sklearn.metrics import confusion_matrix, accuracy_score, precision_recall_fscore_support

print("\n training data = \n", confusion_matrix(Y_tr, Yp_tr, labels = [0,1]))
print("\nAccuracy train data = ", accuracy_score(Y_tr, Yp_tr))
# print("Corr. training data = ", calc_corr(Yp_tr, Y_tr))
print(precision_recall_fscore_support(Y_tr, Yp_tr, pos_label=1))

print("\n test data = \n", confusion_matrix(Y_te, Yp_te, labels = [0,1]))
print("\nAccuracy test data = ",accuracy_score(Y_te, Yp_te))
# print("Corr. test data = ", calc_corr(Yp_te, Y_te))


print(precision_recall_fscore_support(Y_te, Yp_te, pos_label=1))