#!/usr/bin/env python

import sys
import numpy as np
from scipy.io import loadmat
from scipy.stats import zscore
from scipy.signal import detrend

'''

Prepare regressor matrix, originally in MATLAB
detrend and normalized, calculate temporal derivatives (18P) and the quadratric term (36P)
Updates to original command to convert to 36P matrix
Satterthwaite et al., 2013, Neuroimage

Orig MATLAB command:
#matlab -nojvm -nodesktop -nosplash -r "try e=0; format long g; nuis_ts=load('${NUIS_TS}'); \
xx=diff(zscore(detrend(nuis_ts))); x=zscore(detrend(nuis_ts)); xx=[zeros(size(xx(1,1:end)));xx]; \
xxx=[x xx]; dlmwrite('${tmpdir}/nuis_out.dat',xxx,'delimiter', ' ', 'precision',10); catch e=1; end; exit(e)"

'''

def main(NUIS_TS,tmpdir):

    # Load nuisance time series
    nuis_ts = np.loadtxt(NUIS_TS)  # Replace with actual path or pass as a variable

    # Detrend and z-score normalization
    nuis_norm = zscore(detrend(nuis_ts, axis=0), ddof=1, axis=0)

    # First derivative (temporal difference)
    nuis_deriv1 = np.diff(nuis_norm, axis=0)
    nuis_deriv1 = np.vstack([np.zeros((1, nuis_deriv1.shape[1])), nuis_deriv1])

    # Concatenate original + derivative
    nuis_18P = np.hstack([nuis_norm, nuis_deriv1])

    # Square terms
    nuis_quad = nuis_18P ** 2

    # Full nuisance regressor set
    FULLNUISDF = np.hstack([nuis_norm, nuis_deriv1, nuis_quad])

    # Save to file
    np.savetxt(f'{tmpdir}/nuis_out.dat', FULLNUISDF, delimiter=' ', fmt='%.10g')


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python calcualte_nuisance_params.py $NUIS_TS $tmpdir")
    else:
        main(sys.argv[1], sys.argv[2])
