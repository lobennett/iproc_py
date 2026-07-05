%{
This is a standalone version of the previous 
MATLAB implementation of calculate_nuisance_params.py
%}

sub = 'AB123C';
ses = '260101_ABC00123';
scan_no = '001';
task = 'HANDSd0r2';
out_file = 'nuis_out.dat';

% construct path to *_nuis_ts.dat
taskdir = sprintf('%s_%s', task, scan_no);
fname = sprintf('%s_bld%s_reorient_skip_mc_unwarp_anat_nuis_ts.dat', ...
    ses, scan_no);
dat_file = fullfile(sub, 'NAT111', ses, taskdir, fname)

format long g;
nuis_ts = load(dat_file);
nuis_detrend=detrend(nuis_ts);
nuis_norm = zscore(nuis_detrend);

nuis_deriv1 = diff(nuis_norm);
nuis_deriv1 = [zeros(size(nuis_deriv1(1,1:end)));nuis_deriv1];

nuis_18P = [nuis_norm nuis_deriv1];
nuis_quad = nuis_18P .^2;

FULLNUISDF = [nuis_norm nuis_deriv1 nuis_quad];
% precision 10 is equivalent %.10g, not %.10f
dlmwrite(out_file, FULLNUISDF, 'delimiter', ' ', 'precision', 10);
