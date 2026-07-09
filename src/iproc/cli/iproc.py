#!/usr/bin/env python
'''
Main iproc engine. This one script runs the entire data preprocessing pipeline.
'''

import os
import sys
import glob
import time
import pickle
import shutil
import logging
import logging.config
import collections

import argparse as ap
import datetime as dt
import subprocess as sp

import iproc.steps as iProcSteps

import iproc.qc as qc
import iproc.bids as bids
import iproc.commons as commons
import iproc.executors as executors

from iproc import conf,csvHandler
from iproc.config import ConfigError
from pathlib import Path

logger = logging.getLogger(os.path.basename(__file__))

print('-----------------------------------')
print('---- RUNNING MULTI_ECHO IPROC -----')
print('-----------------------------------')
##
# stages
##


def setup(steps,args):

    ########################################
    # STEP 1: get ANAT, BOLD, and Field Maps
    ########################################

    # TODO: none of these steps produce rmfiles, these are totally unneeded.
    rmfiles = []


    #  create dedicated queue folder and clear it out at the beginning
    
    dcm2nii_qdir = os.path.join(
        steps.conf.iproc.OUTDIR,
        steps.conf.iproc.SUB,
        'Q'
    )
    steps.conf.iproc.QDIR = dcm2nii_qdir
    if os.path.exists(dcm2nii_qdir):
        shutil.rmtree(dcm2nii_qdir)
    os.makedirs(dcm2nii_qdir) 
    logger.info('created empty Qdir')

    if args.bids:
        job_spec_list = steps.fmap_from_bids(overwrite=args.overwrite)
        rmfiles += execute(args.executor, job_spec_list,steps, throttle=10, **args.cluster['ingest_fieldmap'])

        job_spec_list = steps.anat_from_bids(overwrite=args.overwrite)
        rmfiles += execute(args.executor, job_spec_list,steps, throttle=10, **args.cluster['ingest_anat'])

        job_spec_list = steps.func_from_bids(overwrite=args.overwrite)
        rmfiles += execute(args.executor, job_spec_list,steps,throttle=10,**args.cluster['ingest_task'])

    else:
        job_spec_list = steps.xnat_to_nii_gz_fieldmap(overwrite=args.overwrite)
        rmfiles += execute(args.executor, job_spec_list,steps, throttle=10, **args.cluster['ingest_fieldmap'])

        job_spec_list = steps.xnat_to_nii_gz_anat(overwrite=args.overwrite)
        rmfiles += execute(args.executor, job_spec_list,steps, throttle=10, **args.cluster['ingest_anat'])

        job_spec_list = steps.xnat_to_nii_gz_task(overwrite=args.overwrite)
        rmfiles += execute(args.executor, job_spec_list,steps,throttle=10,**args.cluster['ingest_task'])

    job_spec_list = QC_fmap(steps,args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps,**args.cluster['fmap_qc'])

    ########################################
    # Kick off recon-all freesurfer
    ########################################
    job_spec_list = steps.recon_all(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps,**args.cluster['recon_all'])

    logger.info("Check quality of Surface Estimation using the following commands:")
    for sessionid,_ in steps.scans.sessions():
        anat_vol = os.path.join(conf.fs.SUBJECTS_DIR,sessionid,'mri','T1.mgz')
        logger.info("surface/T1 match check:")
        logger.info(f"freeview -v {anat_vol} -f {conf.fs.SUBJECTS_DIR}/{sessionid}/surf/lh.pial:edgethickness=1 {conf.fs.SUBJECTS_DIR}/{sessionid}/surf/lh.white:edgecolor=blue:edgethickness=1 {conf.fs.SUBJECTS_DIR}/{sessionid}/surf/rh.pial:edgethickness=1 {conf.fs.SUBJECTS_DIR}/{sessionid}/surf/rh.white:edgecolor=blue:edgethickness=1")
        logger.info("spherical registration fsaverage alignment check:")
        logger.info(f"freeview -f {conf.fs.SUBJECTS_DIR}/{sessionid}/surf/lh.sphere.reg:overlay=lh.sulc:{conf.fs.SUBJECTS_DIR}/{sessionid}/surf/lh.sulc:overlay_threshold=0,1 -viewport 3d -camera Elevation 60")
        logger.info("The threshold is either 0,1 or 0,10 (depending on the individual, and this can be adjusted)")
    logger.info("compare this to fsaverage6:")
    logger.info(f"freeview -f {conf.fs.SUBJECTS_DIR}/fsaverage6/surf/lh.sphere.reg:overlay=lh.sulc:{conf.fs.SUBJECTS_DIR}/fsaverage6/surf/lh.sulc:overlay_threshold=0,1 -viewport 3d -camera Elevation 60")

    logger.info("Scans downloaded from XNAT and freesurfer recon_all completed")
    logger.info("Define T1_SESS in [T1] section of conf file from the best session.")
    logger.info("finished with setup step! next step is 'bet' step")
    return rmfiles


def QC_fmap(steps,overwrite):

    #TODO: would be nice to just get a list made from steps.py
    merge_filter = 'reorient_skip'
    # set up qc objects
    qc_ax = qc.qc_pdf_maker(conf,'ax')
    qc_sag = qc.qc_pdf_maker(conf,'sag')
    # create the t1 pages
    ax_slicer = {'window_dims':'0 100 0 100 5 55'.split(' '),
                        # <xmin> <xsize> <ymin> <ysize> <zmin> <zsize>
                        'sample': '1', # nth image to sample
                        'width': 7} # Number of images across, I think

    sag_slicer = {'window_dims':'0 100 0 100 15 60'.split(' '),
                        # <xmin> <xsize> <ymin> <ysize> <zmin> <zsize>
                        'sample': '1', # nth image to sample
                        'width': 8} # Number of images across, I think

    task_ax_slicer = ax_slicer
    task_sag_slicer = sag_slicer
    for sessionid,_ in steps.scans.sessions():
        # scanno:scan_object for bold scans
        bold_dict = {int(bold_scan['BLD']):bold_scan for _,bold_scan in steps.scans.tasks()}
        print(bold_dict)

        for fmap_dir,fmap_scans in steps.scans.fieldmaps():
            fmap1_no = fmap_scans['FIRST_FMAP']
            #fmap1_no_pad = "%03d" % int(fmap1_no)
            fmap1_no_pad = f'{int(fmap1_no):03d}'
            fmap_dirname = f'{fmap_dir}_{fmap1_no_pad}'

            # add BOLD page
            bold_scan = nearby_bold(bold_dict,int(fmap1_no))
            scan_no = bold_scan['BLD']
            task_type = bold_scan['TYPE']
            #bold_no = "%03d" % int(scan_no)
            bold_no = f'{int(scan_no):03d}'
            task_dirname = f'{task_type}_{bold_no}'
            #spacename = "%s_bld%s_%s" % (sessionid,bold_no,merge_filter)
            spacename = f'{sessionid}_bld{bold_no}_{merge_filter}' #% (sessionid,bold_no,merge_filter)

            infile = os.path.join(conf.iproc.NATDIR,sessionid,task_dirname,spacename+'.nii.gz')

# --- IF IT'S A MULTI-EHCO BOLD VOLUME, PICK THE FIRST ECHO! ---
            if not os.path.isfile(infile):

                infile = os.path.join(conf.iproc.NATDIR,sessionid,task_dirname,spacename+'_e1.nii.gz')

            task_page_sag = qc.page(infile,task_sag_slicer)
            task_page_ax = qc.page(infile,task_ax_slicer)
            qc_sag.pages.append(task_page_sag)
            qc_ax.pages.append(task_page_ax)

            # add fmap page
            fmap_full_dirname = os.path.join(steps.conf.iproc.NATDIR,sessionid,fmap_dirname)

            if steps.conf.fmap.PREPTOOL == 'topup':
                target_fmap_nii = f'{fmap_full_dirname}/{sessionid}_{fmap1_no_pad}_fieldmap_masked.nii.gz' #topup not masked
            else:
                target_fmap_nii = f'{fmap_full_dirname}/{sessionid}_{fmap1_no_pad}_fieldmap.nii.gz'

            fmap_page_sag = qc.page(target_fmap_nii,task_sag_slicer)
            fmap_page_ax = qc.page(target_fmap_nii,task_ax_slicer)
            qc_sag.pages.append(fmap_page_sag)
            qc_ax.pages.append(fmap_page_ax)
    returnval = []
    ax_job = qc_ax.produce_pdf('fmap',save_intermediates=steps.args.no_remove_files,overwrite=overwrite)
    if ax_job:
        returnval.append(ax_job)
    sag_job = qc_sag.produce_pdf('fmap',save_intermediates=steps.args.no_remove_files,overwrite=overwrite)
    if sag_job:
        returnval.append(sag_job)
    logger.debug(returnval)
    return returnval

def nearby_bold(bold_dict,scan_no):
    # Takes in a bold dict which indexes bold_scan objects by 
    # integer-form aquisition number
    # also takes in scan_no, an integer 
    i=scan_no
    # get the lowest scan number in bold list
    first_scan = int(min(list(bold_dict.keys())))
    while i>first_scan:
        i=i-1
        try:
            bold_scan = bold_dict[i]  
            return bold_scan
        except KeyError:
            continue
    i=scan_no
    # get the highest scan number in bold list
    last_scan = int(max(list(bold_dict.keys())))
    while i<last_scan:
        i=i+1
        try:
            bold_scan = bold_dict[i]  
            return bold_scan
        except KeyError:
            continue
    logger.error(f'{scan_no} not found in {bold_dict}')
    raise KeyError
        
def check_bet(steps,args):
    # before you run this stage, be sure to run freesurfer, check the quality of the output

    rmfiles=[]
    #steps.load_rmfile_dump('setup')
    # STEP 1: Calculate warp from mean BOLD to T1
    job_spec_list = steps.sesst_prep(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps,**args.cluster['sesst_prep'])

    mpr_bet()

    # not needed, as this stage produces no rmfiles
    #os.rename(steps.rm_dump_filename,steps.rm_final_filename)

    logger.info("finished with bet step! next step is 'unwarp_motioncorrect_align' step")

    return rmfiles

def mpr_bet():
    betcmd = f"bet {conf.template.TEMPLATE_DIR}/{conf.T1.T1_SESS}_mpr_reorient {conf.template.TEMPLATE_DIR}/{conf.T1.T1_SESS}_mpr_reorient_brain -m -R -v"
    fslview = f"fslview {conf.template.TEMPLATE_DIR}/{conf.T1.T1_SESS}_mpr_reorient*"
    explain_bet(betcmd,fslview)

def unwarp_motioncorrect_align(steps,args):

    rmfiles = []
    # still needed, as we might need to load from a crashed unwarp_motioncorrect_align run.
    nat_brain = f'{conf.template.TEMPLATE_DIR}/mpr_reorient_brain.nii.gz'
    try:
        os.stat(nat_brain)
    except OSError:
        logger.error(f'{nat_brain} not found, ')
        mpr_bet()
        raise IOError(f'{nat_brain} not found, quitting')
    steps.load_rmfile_dump(None,initialize_blank=True)
    ########################################
    # Step 1: (substeps should be sequential)
    ########################################
    # a) Extract middle volume of scan from Session1 acquired closest in time to the field map
    job_spec_list = steps.fslroi_reorient_skip(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['fslroi_reorient_skip'])

    # b) Extract middle volume of scan from Session1 acquired closest in time to the field map
    # and unwarp midvol image using fieldmap
    job_spec_list = steps.fm_unwarp_midvol(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['fm_unwarp_midvol'])

    # temp for fm testing

    ### ------------------------------------------------------ ###
    ### ----- SKIP THIS for native BOLD space 2024.10.04 ----- ###
    ### ------------------------------------------------------ ###

    # c) Upsample to create midvol target:
    job_spec_list = steps.create_upsamped_midvol_target(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['create_upsampled_midvol_target'])

    ########################################
    # STEP 2: Motion correct each run with mcflirt, and register all runs to
    # unwarped midvol target produced from the midvol of midvol_sess specified in conf
    ########################################

    job_spec_list = steps.fm_unwarp_and_mc_to_midvol(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['fm_unwarp_and_mc_to_midvol'])

    ########################################
    # STEP 3: Calculate warp to mean BOLD midvol template produced by averaging
    # the output of fm_unwarp_and_mc_to_midvol.

    ########################################


    ### ------------------------------------------------------ ###
    ### --- TO native BOLD space (NOT 1.2 MM3) 2024.10.04 ---- ###
    ### ------------------------------------------------------ ###

    # create mean bold midvol template
    merge_filter = 'reorient_skip_mc_unwarp_midvol_to_midvoltarg'
    # flirt output from fm_unwarp_and_mc_to_midvol
    merge_glob1 = conf.iproc.NATDIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    merge_glob2 = conf.iproc.NATDIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}_e?.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    globfiles_tomerge = get_glob_or(args,merge_glob1,merge_glob2)

    # was standard_midvol_on_midvoltarg_allscansmean
    # conf.template.midvols mean is used in the next step, so is defined in main
    job_spec_list = steps.fslmerge_meantime(conf.template.midvols_mean,globfiles_tomerge,overwrite=args.overwrite)
    logger.info('merging BOLD scans')
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fslmerge_meantime_midvols'])

    job_spec_list = steps.align_to_midvol_mean(overwrite=args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['align_to_midvol_mean'])

    ## end of computational steps for unwarp_motioncorrect_align stage

    ########################
    # QC1 mean of bold midvol and fm_unwarp_and_mc_to_midvol output to pdf
    ########################

    print('*****QC1*****')
    qc_pdfs = []
    job_spec_list = QC_unwarp_motioncorrect_align(steps,merge_filter,conf.template.midvols_mean,args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['midvol_qc'])
    qc_pdfs += [job_spec.outfiles for job_spec in job_spec_list]

    ########################
    # QC2 checks output of align_to_midvol_mean
    ########################

    # get mean of flirt output from align_to_midvol_mean, which is the
    # product of registering the BOLD to the mean of BOLD midvols
    print('*****QC2*****')
    merge_filter='on_midmean'
    merge_glob = conf.iproc.NATDIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    globfiles_tomerge = get_glob(args,merge_glob)
    # was standard_midvol_on_allscansmean.nii.gz
    # going to just call meanbold, don't think this is used later on in the pipeline anyway
    template_fname = 'meanbold_midvols_on_midmean.nii.gz'
    conf.template.meanbold = os.path.join(conf.template.TEMPLATE_DIR,template_fname)

    job_spec_list = steps.fslmerge_meantime(conf.template.meanbold,globfiles_tomerge,overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fslmerge_meantime_midmean'])

    job_spec_list = QC_unwarp_motioncorrect_align(steps,merge_filter,conf.template.meanbold,args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['midmean_qc'])
    qc_pdfs += [job_spec.outfiles for job_spec in job_spec_list]

    for qc_pdf in qc_pdfs:
        logger.info(qc_pdf)
    logger.info('done with unwarp_motioncorrect_align preprocessing! Check QC PDFs above by flipping through and looking for major changes in the location of sulci and gyri, then proceed to T1_warp_and_mask')
    if os.path.exists(steps.rm_dump_filename):
        # if this is a rerun, we would want to skip that bc the rm_dump_filename will not exist
        os.rename(steps.rm_dump_filename,steps.rm_final_filename)

    return rmfiles


def QC_unwarp_motioncorrect_align(steps, merge_filter,template,overwrite):
    print('******QC_unwarp_motioncorrect_align*****')
    # set up qc objects
    qc_ax = qc.qc_pdf_maker(conf,'ax')
    qc_sag = qc.qc_pdf_maker(conf,'sag')
    # create the t1 pages
    #ax_slicer = {'window_dims':'10 160 10 160 20 105'.split(' '),
    ax_slicer = {'window_dims':'10 160 10 160 20 105'.split(' '),
                        # <xmin> <xsize> <ymin> <ysize> <zmin> <zsize> (for fslroi)
                        'sample': '1', # todo: what is this
                        'width': 14} # Number of images across, I think
    page_ax = qc.page(template,ax_slicer)
    qc_ax.pages.append(page_ax)

    # changed from zmin=30
    sag_slicer = ax_slicer
    page_sag = qc.page(template,sag_slicer)
    qc_sag.pages.append(page_sag)

    task_ax_slicer = ax_slicer
    task_sag_slicer = sag_slicer
    for sessionid,_ in steps.scans.sessions():
        for task_type,bold_scan in steps.scans.tasks():
            scan_no = bold_scan['BLD']
            bold_no = "%03d" % int(scan_no)
            task_dirname = f'{task_type}_{bold_no}'
            spacename = f"{sessionid}_bld{bold_no}_{merge_filter}"
            infile = os.path.join(conf.iproc.NATDIR,sessionid,task_dirname,spacename+'.nii.gz')
            if not os.path.isfile(infile):
            	infile = os.path.join(conf.iproc.NATDIR,sessionid,task_dirname,spacename+'_e1.nii.gz')
            task_page_sag = qc.page(infile,task_sag_slicer)
            task_page_ax = qc.page(infile,task_ax_slicer)
            qc_sag.pages.append(task_page_sag)
            qc_ax.pages.append(task_page_ax)
    returnval = []
    ax_job = qc_ax.produce_pdf(merge_filter,save_intermediates=steps.args.no_remove_files,overwrite=overwrite)
    if ax_job:
        returnval.append(ax_job)
    sag_job = qc_sag.produce_pdf(merge_filter,save_intermediates=steps.args.no_remove_files,overwrite=overwrite)
    if sag_job:
        returnval.append(sag_job)
    return returnval

##
# warp point
##
# past this point we're working with output spaces
def T1_warp_and_mask(steps,args):

    steps.load_rmfile_dump('unwarp_motioncorrect_align')
    rmfiles = []
    ########################################
    job_spec_list = steps.bbreg(overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['bbreg'])

    logger.info('Calculate warp from native T1 to MNI space')
    job_spec_list = steps.compute_T1_MNI_warp(overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['compute_T1_MNI_warp'])

    logger.info('register MNI csf and wm masks to T1 space')
    job_spec_list = steps.reg_MNI_CSF_WM_to_T1(overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['reg_MNI_CSF_WM_to_T1'])

    fnirt_bet_reminder()
    #os.rename(steps.rm_dump_filename,steps.rm_final_filename)
    # ( no rmfiles are added during this stage, so no crashfile is created)
    logger.info("finished with T1_warp_and_mask step! next step is 'combine_and_apply_warp' step")
    return rmfiles

def fnirt_bet_reminder():
    betcmd = f'bet {conf.template.TEMPLATE_DIR}/anat_mni_underlay.nii.gz {conf.template.TEMPLATE_DIR}/anat_mni_underlay_brain -m -R -v'
    fslviewcmd = f'fslview {conf.template.TEMPLATE_DIR}/anat_mni_underlay*'
    explain_bet(betcmd,fslviewcmd)

def explain_bet(betcmd,fslviewcmd):
    logger.info('iProc has copied the recon-all brain mask and brain extracted')
    logger.info('images into the template folder.')
    logger.info('')
    logger.info('BEFORE PROCEEDING, run the following command to check:')
    logger.info('')
    logger.info(fslviewcmd)
    logger.info('')
    logger.info('A good brain mask should have minimal non-brain tissue and not trim any brain.')
    logger.info('If the brain mask looks good, proceed to the next step and DISREGARD MANUAL STEPS BELOW')
    logger.info('')
    logger.info('If the brain mask DOES NOT look good, you can perform manual brain')
    logger.info('extraction using iterative FSL bet commands shown below')
    logger.info('')
    logger.info('1) run the following command:')
    logger.info(betcmd)
    logger.info('2) copy down the final c-of-g values, call them x y z')
    logger.info('3) check output and adjust for a new bet command.')
    logger.info('')
    logger.info(fslviewcmd)
    logger.info('')
    logger.info('4) adjust for a new bet command')
    logger.info('   for example:')
    new_betcmd = betcmd + ' -c x y z+10 '
    logger.info(new_betcmd)
    logger.info('')
    logger.info("Feel free  to try other options from `bet --help`.")
    logger.info("Adjusting the center, and lowering -f, has given us the best results")
    logger.info('') 
    logger.info('5) finally, record your changes! A good idea is to store them in a text file in your templates folder named bet.txt')
    logger.info('copy your own commands into the sample template below')
    logger.info(f'echo "YOUR BET CMD" >> {conf.template.TEMPLATE_DIR}/logs/bet.txt')


def combine_and_apply_warp(steps,args):

    # load from unwarp_motioncorrect_align, T1_warp_and_mask doesn't add any rmfiles
    steps.load_rmfile_dump('unwarp_motioncorrect_align')
    rmfiles = []
    ########################################
    mni_underlay_brain = f'{conf.template.TEMPLATE_DIR}/anat_mni_underlay_brain.nii.gz'
    if not os.path.exists(mni_underlay_brain):
        logger.error(f'{mni_underlay_brain} not found, quitting')
        fnirt_bet_reminder()
        raise IOError(f'{mni_underlay_brain} not found, quitting')

    
    logger.info('dilate mask to use in reducing volume size')
    job_spec_list = steps.size_brainmask(overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['size_brainmask'])

    logger.info('combine warps to project data to output T1 space')
    parallel_job_spec_list = steps.combine_warps_parallel(anat_space='T1',overwrite=args.overwrite)
    
    # this is where  we transfer to NAT222
    post_job_spec_list = steps.combine_warps_post(overwrite=args.overwrite)

    # package cluster args for dependent jobs
    kwargs = args.cluster['combine_warps_post_anat']
    if kwargs['RUNMODE'] == 'run':
        del kwargs['RUNMODE']
        print(len(parallel_job_spec_list))
        print(len(post_job_spec_list))
        ###assert len(parallel_job_spec_list) == len(post_job_spec_list)
        for parallel_job,post_job in zip(parallel_job_spec_list,post_job_spec_list):
            parallel_job.afterok.append((post_job,kwargs))

    rmfiles += execute(args.executor,parallel_job_spec_list,steps,throttle=10,**args.cluster['combine_warps_parallel_anat'])
    anat_anatdir = os.path.join(conf.iproc.NAT_RESAMP_DIR,'ANAT')
    if not os.path.isdir(anat_anatdir):
        os.makedirs(anat_anatdir)
    mpr_reorient = os.path.join(conf.template.TEMPLATE_DIR,'mpr_reorient.nii.gz')
    anat_link = ['cp', '-f',mpr_reorient,anat_anatdir]
    commons.check_call(anat_link)

    logger.info('combine warps to project data to MNI space')
    parallel_job_spec_list = steps.combine_warps_parallel(anat_space='MNI',overwrite=args.overwrite)

    # this is where we transfer to MNI222!!!
    post_job_spec_list = steps.combine_warps_post_MNI(overwrite=args.overwrite)
    kwargs = args.cluster['combine_warps_post_mni']
    if kwargs['RUNMODE'] == 'run':
        del kwargs['RUNMODE']
        ###assert(len(parallel_job_spec_list) == len(post_job_spec_list))
        for parallel_job,post_job in zip(parallel_job_spec_list,post_job_spec_list):
            parallel_job.afterok.append((post_job,kwargs))
    rmfiles += execute(args.executor,parallel_job_spec_list,steps,throttle=10,**args.cluster['combine_warps_parallel_mni'])

    # copy mni anat to output dir
    mni_anatdir = os.path.join(conf.iproc.MNI_RESAMP_DIR,'ANAT')
    if not os.path.isdir(mni_anatdir):
        os.makedirs(mni_anatdir)
    anat_mni_underlay = os.path.join(conf.template.TEMPLATE_DIR,'anat_mni_underlay.nii.gz')
    anat_link = ['cp', '-f',anat_mni_underlay,mni_anatdir]
    commons.check_call(anat_link)

    #########################
    # QC PDF generation
    #########################
    qc_pdfs = []
    ## NAT222
    # mean_out from combine_warps_post
    merge_filter = 'reorient_skip_mc_unwarp_anat_mean'
    merge_glob1 = conf.iproc.NAT_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    merge_glob2 = conf.iproc.NAT_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}_e?.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    globfiles_tomerge = get_glob_or(args,merge_glob1,merge_glob2)
    template_fname = f'NAT{conf.out_atlas.RESOLUTION}_meanvol_allscansmean.nii.gz'
    template = os.path.join(conf.template.TEMPLATE_DIR,template_fname)

    ## adapted from ./QC/iProc_QC_T1nativespace_meanBOLDS.py
    job_spec_list = steps.fslmerge_meantime(template,globfiles_tomerge,overwrite=args.overwrite)
    logger.info('merging BOLD scans')
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fslmerge_meantime_anat_mean'])


    # NAT222_meanvol
    def nat_mean_taskname(sessionid,bold_no,merge_filter,midvol_pad):
        spacename = f'{sessionid}_bld{bold_no}_{merge_filter}'
        return spacename

    header_images={}
    header_images['t1'] = mpr_reorient
    header_images['template'] = template

    anat_ax_slicer = {'window_dims':'30 220 30 220 44 128'.split(' '),
                        # <xmin> <xsize> <ymin> <ysize> <zmin> <zsize>
                        'sample': '2', # todo: what is this
                        'width': 15} # Number of images across, I think
    anat_sag_slicer = {'window_dims':'30 220 30 220 44 128'.split(' '),
                        'sample': '2', # sample every 'n'th images
                        'width': 16} # w*180 = max width
    outdir = conf.iproc.NAT_RESAMP_DIR
    job_spec_list = QC_warp(steps, outdir,merge_filter,header_images,anat_ax_slicer,anat_sag_slicer,nat_mean_taskname, args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['anat_mean_qc'])
    qc_pdfs += [job_spec.outfiles for job_spec in job_spec_list]

    # NAT222_midvol
    # midvol_out from combine_warps_post
    merge_filter='reorient_skip_mc_unwarp_anat_vol'
    merge_glob1 = conf.iproc.NAT_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}???.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    merge_glob2 = conf.iproc.NAT_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}???_e?.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    globfiles_tomerge = get_glob_or(args,merge_glob1,merge_glob2)
    template_fname = f'NAT{conf.out_atlas.RESOLUTION}_midvol_allscansmean.nii.gz'
    template = os.path.join(conf.template.TEMPLATE_DIR,template_fname)

    ## adapted from ./QC/iProc_QC_T1nativespace_midvolBOLDS.py
    job_spec_list = steps.fslmerge_meantime(template,globfiles_tomerge,overwrite=args.overwrite)
    logger.info('merging BOLD scans')
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fslmerge_meantime_anat_midvols'])


    def nat_mid_taskname(sessionid,bold_no,merge_filter,midvol_pad):
        spacename = f'{sessionid}_bld{bold_no}_{merge_filter}{midvol_pad}'
        return spacename
    header_images={}
    header_images['t1'] = mpr_reorient
    header_images['template'] = template
    job_spec_list = QC_warp(steps, outdir,merge_filter,header_images,anat_ax_slicer,anat_sag_slicer,nat_mid_taskname, args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['anat_midvols_qc'])
    qc_pdfs += [job_spec.outfiles for job_spec in job_spec_list]

    ####
    ## MNI
    # MNI222_meanvol
    merge_filter = 'reorient_skip_mc_unwarp_anat_mni_mean'
    merge_glob1 = conf.iproc.MNI_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    merge_glob2 = conf.iproc.MNI_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}_e?.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    globfiles_tomerge = get_glob_or(args,merge_glob1,merge_glob2)
    # from QC/iProc_QC_MNIspace_meanBOLDS.py
    template_fname = f'MNI{conf.out_atlas.RESOLUTION}_meanvol_allscansmean.nii.gz'
    templatefile = os.path.join(conf.template.TEMPLATE_DIR,template_fname)

    job_spec_list = steps.fslmerge_meantime(templatefile,globfiles_tomerge,overwrite=args.overwrite)
    logger.info('merging BOLD scans')
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fslmerge_meantime_mni_mean'])

    header_images={}
    header_images['t1'] = anat_mni_underlay
    header_images['template'] = templatefile
    mni_ax_slicer = {'window_dims':'0 170 0 200 30 140'.split(' '),
                        # <xmin> <xsize> <ymin> <ysize> <zmin> <zsize>
                        'sample': '2', # todo: what is this
                        'width': 14} # Number of images across, I think

    mni_sag_slicer = {'window_dims':'10 200 0 160 20 140'.split(' '),
                        'sample': '2', # sample every 'n'th images
                        'width': 16} # w*180 = max width


    def mean_task_spacename(sessionid,bold_no,merge_filter,midvol_pad):

        spacename = "%s_bld%s_%s" % (sessionid,bold_no,merge_filter)
        return spacename
    outdir = conf.iproc.MNI_RESAMP_DIR
    job_spec_list =  QC_warp(steps, outdir,merge_filter,header_images,mni_ax_slicer,mni_sag_slicer,mean_task_spacename, args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['mni_mean_qc'])
    qc_pdfs += [job_spec.outfiles for job_spec in job_spec_list]
    logger.info('creating QC pdfs')

    # MNI222_midvol
    merge_filter='reorient_skip_mc_unwarp_anat_mni_vol'
    merge_glob1 = conf.iproc.MNI_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}???.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    merge_glob2 = conf.iproc.MNI_RESAMP_DIR + '/{SESS}/{TASK}/{SESS}_bld???_{STEPS}???_e?.nii.gz'.format(SESS='*',TASK='*',STEPS=merge_filter)
    globfiles_tomerge = get_glob_or(args,merge_glob1,merge_glob2)
    template_fname = f'MNI{conf.out_atlas.RESOLUTION}_midvol_allscansmean.nii.gz'
    templatefile = os.path.join(conf.template.TEMPLATE_DIR,template_fname)

    job_spec_list = steps.fslmerge_meantime(templatefile,globfiles_tomerge,overwrite=args.overwrite)
    logger.info('merging BOLD scans')
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fslmerge_meantime_mni_midvols'])

    header_images={}
    header_images['t1'] = anat_mni_underlay
    header_images['template'] = templatefile

    
    #MNI222_midvol
    def mid_task_spacename(sessionid,bold_no,merge_filter,midvol_pad):
        spacename = "%s_bld%s_%s%s" % (sessionid,bold_no,merge_filter,midvol_pad)
        return spacename
    job_spec_list =  QC_warp(steps, outdir,merge_filter,header_images,mni_ax_slicer,mni_sag_slicer,mid_task_spacename, args.overwrite)
    rmfiles += execute(args.executor, job_spec_list,steps, **args.cluster['mni_midvols_qc'])
    qc_pdfs += [job_spec.outfiles for job_spec in job_spec_list]
    logger.info('creating QC pdfs')

    for qc_pdf in qc_pdfs:
        logger.info(qc_pdf)
    logger.info('done with warping! Check QC PDFs by flipping through and looking for major changes in the location of sulci and gyri, before proceeding to filter_and_project.')
    #os.rename(steps.rm_dump_filename,steps.rm_final_filename)
    # all produced rmfiles are consumed internally
    return rmfiles

def QC_warp(steps, outdir,merge_filter,header_images,ax_slicer,sag_slicer,task_spacename, overwrite):
    # set up qc objects
    qc_ax = qc.qc_pdf_maker(conf,'ax')
    qc_sag = qc.qc_pdf_maker(conf,'sag')
    # create the template pages
    template_img= header_images['template']
    # slicer params are the same as the meanvol section above.
    template_page_ax = qc.page(template_img,ax_slicer)
    template_page_sag = qc.page(template_img,sag_slicer)
    qc_ax.pages.append(template_page_ax)
    qc_sag.pages.append(template_page_sag)
    # create the T1 pages
    t1_img= header_images['t1']
    anat_page_ax = qc.page(t1_img,ax_slicer)
    qc_ax.pages.append(anat_page_ax)
    anat_page_sag = qc.page(t1_img,sag_slicer)
    qc_sag.pages.append(anat_page_sag)

    # create task pages
    for sessionid,_ in steps.scans.sessions():
            for task_type,bold_scan in steps.scans.tasks():
                scan_no = bold_scan['BLD']
                bold_no = "%03d" % int(scan_no)
                task_dirname = f'{task_type}_{bold_no}'
                numvol = steps.scans.task_dict[task_type]['NUMVOL']
                numechos=steps.scans.task_dict[task_type]['NUMECHOS']
                midvol_num = str(int(numvol)//2)
                midvol_pad = midvol_num.zfill(3)
                spacename = task_spacename(sessionid,bold_no,merge_filter,midvol_pad)
                if int(numechos) == 1:
                	infile = os.path.join(outdir,sessionid,task_dirname,spacename+'.nii.gz')
                else:
                	infile = os.path.join(outdir,sessionid,task_dirname,spacename+'_e1.nii.gz')
                task_page_sag = qc.page(infile,sag_slicer)
                task_page_ax = qc.page(infile,ax_slicer)
                qc_sag.pages.append(task_page_sag)
                qc_ax.pages.append(task_page_ax)
    joblist = []
    ax_job = qc_ax.produce_pdf(merge_filter,save_intermediates=steps.args.no_remove_files,overwrite=overwrite)
    if ax_job:
       joblist.append(ax_job) 
    sag_job = qc_sag.produce_pdf(merge_filter,save_intermediates=steps.args.no_remove_files,overwrite=overwrite)
    if sag_job:
       joblist.append(sag_job) 
    return joblist

def filter_and_project(steps, args):

    steps.load_rmfile_dump('unwarp_motioncorrect_align')
    rmfiles = []
    ########################################

    ## Single-echo: calc nuisance, nuisance regress, bandpass, wholebrain, and projec to surf ###
    ### Multi-echo: only calc nuisance, bandpass, and projec to surf

    job_spec_list = steps.calculate_nuisance_params(overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['calculate_nuisance_params'])
    ## can these be run all at the same time? I think so

    #MNI
    res = conf.out_atlas.RESOLUTION
    job_spec_list = steps.nuisance_regress(f'MNI{res}', overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['nuisance_regress_mni'])
    job_spec_list = steps.bandpass(f'MNI{res}', overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['bandpass_mni'])
    job_spec_list = steps.wholebrain_only_regress(f'MNI{res}', overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['wholebrain_only_regress_mni'])

    #T1
    job_spec_list = steps.nuisance_regress(f'NAT{res}', overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['nuisance_regress_anat'])
    job_spec_list = steps.bandpass(f'NAT{res}', overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['bandpass_anat'])
    job_spec_list = steps.wholebrain_only_regress(f'NAT{res}', overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['wholebrain_only_regress_anat'])

    # step 6
    job_spec_list = steps.fs6_project_to_surface(overwrite=args.overwrite)
    rmfiles += execute(args.executor,job_spec_list,steps,**args.cluster['fs6_project_to_surface']) #maybe 150GB

    logger.info('iProc completed')
    #os.rename(steps.rm_dump_filename,steps.rm_final_filename)
    # does not add any rmfiles
    return rmfiles

##
# helpers
##

def execute(executor_type, job_spec_list,steps, **kwargs):
    # short-circuit if step is set to "SKIP"
    if kwargs['RUNMODE'] == 'SKIP':
        logger.info('skipping jobs in job list')
        return []
    elif kwargs['RUNMODE'] == 'run':
        pass
    del kwargs['RUNMODE']
    logger.info('running jobs in job list')
    #TODO: put in rerun_on_fail for flaky steps
    skip_fail = steps.args.skip_fail
    # If I had to do again would make executor class to store this
    if steps.args.dry_run:
        for job in job_spec_list:
            job.dummy = True
    ## attach wrappers
    if steps.args.singularity:
        for j in job_spec_list:
            # check for empty command
            if j.skip:
                continue
            wrapper = os.path.join(conf.iproc.CODEDIR, 'wrappers','singularity_wrap.sh')
            if steps.args.no_srun :
                srun = "NO"
            else:
                srun = "YES"
            def cpu(kwargs):
                try:
                    return str(kwargs['cpu'])
                except KeyError:
                    return str(1)
            #ncf specific, will have to abstract
            singularity_prefix = ['singularity', 'exec', '-e', steps.args.singularity, wrapper, conf.fs.SUBJECTS_DIR, srun, cpu(kwargs)]
            j.prepend_cmd(singularity_prefix)
            for dependent_job,_ in afterok_jobs(j):
                dependent_job.prepend_cmd(singularity_prefix)

    # non-singularity wrapper handling
    if steps.args.wrap:
        wrapper = os.path.join(conf.iproc.CODEDIR,'wrappers',steps.args.wrap)

    if steps.args.user_wrap:
        wrapper = steps.args.user_wrap

    if steps.args.user_wrap or steps.args.wrap:
        for j in job_spec_list:
            if j.skip:
                continue
            prefix = [wrapper]
            if steps.args.wrap_args:
                prefix = prefix+steps.args.wrap_args
            j.prepend_cmd(prefix)
            for dependent_job,_ in afterok_jobs(j):
                dependent_job.prepend_cmd(prefix)

    try:
        # could refactor all this to have child classes of executor object with internal type-specific logic, called here
        if executor_type == 'local':
            for job in job_spec_list:
                # check for empty command
                if job.skip:
                    continue
                if job.dummy:
                    logger.info(job.cmd)
                    continue
                timestamp = time.time()
                hostname = commons.check_output(['hostname']).strip()
                job.stdout = job.logfile_base + f'_{hostname}_{timestamp}.out'
                job.stderr = job.logfile_base + f'_{hostname}_{timestamp}.err'
                stdout = open(job.stdout, 'w')
                stderr = open(job.stderr, 'w')
                logger.debug(job.cmd)
                # run cmd, throw error if it fails
                try:
                    logger.debug(f'running {job.cmd}')
                    commons.check_call(job.cmd, stdout=stdout, stderr=stderr)
                    job.state = 'COMPLETED'
                except Exception as e:
                    logger.info(f'local script has failed: {e}')
                    logger.info(job.stdout)
                    logger.info(job.stderr)
                    stdout.close()
                    stderr.close()
                    if skip_fail:
                        continue
                    raise commons.FailedJobError(job)
                # run any dependent/afterok jobs
                for dependent,_ in job.afterok:
                    dependent.stdout = job.logfile_base + f'_{hostname}_{timestamp}.out'
                    try:
                        logger.debug(f'running dependent job: {dependent.cmd}')
                        commons.check_call(dependent.cmd, stdout=stdout, stderr=stderr)
                        dependent.state = 'COMPLETED'
                    except Exception as e:
                        logger.error(f'dependent job as failed {dependent.cmd}')
                        logger.error(f'stdout: {job.stdout}')
                        logger.error(f'stderr: {job.stderr}')
                        stdout.close()
                        stderr.close()
                        if skip_fail:
                            continue
                        raise commons.FailedJobError(dependent)
        elif executor_type in ['slurm', 'pbsubmit']:
            if executor_type=='slurm':
                if steps.args.sbatch_args: 
                    sbatch_arg_dict = {str(x):y for x,y in zip(list(range(len(steps.args.sbatch_args))),steps.args.sbatch_args)}
                    kwargs.update(sbatch_arg_dict)
            if executor_type == 'pbssubmit':
                if steps.args.interval > 2:
                    logger.warn('PBS forgets completed jobs every 2 minutes or so. Choose a shorter polling interval')
                    logger.warn('On the Martinos center, ')
            executor = executors.get(executor_type)
            if not job_spec_list:
                logger.debug('empty job_spec_list')
                return []
            throttle_no = kwargs.get('throttle', False)
            if throttle_no:
                job_limit = throttle_no
            else:
                job_limit = float('inf')
            if steps.args.single_file:
                #never mind the above, set to 1
                job_limit = 1
            jobspec_kwargs=[]
            for job_spec in job_spec_list:
                # check for empty command
                kwargs_prep(kwargs,steps.args)
                jobspec_kwargs.append((job_spec,kwargs))
                if job_spec.afterok:
                    for dependent_pair in job_spec.afterok:
                        # for now, dependent jobs only play nice with throttling when there is one per job.
                        dependent_job,afterok_kwargs=dependent_pair
                        # skip afterOK part if parent job is a skipped job
                        kwargs_prep(afterok_kwargs,steps.args)
                        jobspec_kwargs.append((dependent_job,afterok_kwargs))
            if jobspec_kwargs:
                if skip_fail:
                    cancel=False
                else:
                    cancel=True

                pickle_file = os.path.join(conf.iproc.RMFILE_DUMP, "save.p")
                pickle.dump( jobspec_kwargs, open(pickle_file, "wb" ) )                
                executors.rolling_submit(executor,jobspec_kwargs,job_limit,steps.args.interval,cancel_on_fail=cancel)
        else:
            raise NotImplementedError(f'executor type {executor_type} is not supported')
    except commons.FailedJobError as e:
        post_process_jobs(job_spec_list,steps.args)
        raise e
    post_process_jobs(job_spec_list,steps.args)
    rmfiles = rmfiles_from_job_specs(job_spec_list)
    if rmfiles:
        return rmfiles
    else:
        # so += works wherever we're calling this function from
        return []

def afterok_jobs(j):
    if j.afterok:
        for dependent_pair in j.afterok:
            dependent_job,kwargs = dependent_pair
            while dependent_job:
                yield(dependent_job,kwargs)
                if dependent_job.afterok:
                    next_level_job,next_kwargs = dependent_job.afterok
                    dependent_job = next_level_job
                    kwargs = next_kwargs
                else:
                    break

def post_process_jobs(job_spec_list, args):
    # process job list after it has been run through an executor
    # compile all jobs and dependencies
    jobs=[]
    for job in job_spec_list:
        jobs.append(job)
        for j,_ in afterok_jobs(job):
            jobs.append(j)
    die = False
    for job in jobs:
        logger.debug(vars(job))
        if job.state == 'COMPLETED':
            # copy outfiles to destination directory, append rmfiles to object and file.
            logger.debug('execution finished successfully. Produced the following files:')
            logger.debug(job.outfiles)
            if args.autodiff:
                die = autodiff(job,args) or die
            # job succeeded, copy logfile
            # TODO: this may not work for pbsubmit.
            # The job.stdout must be an existing valid file path.
            for outdir in job.outfile_dirs:
                if not os.path.isdir(outdir):
                    os.makedirs(outdir)
                if job.stdout:
                    shutil.copy2(job.stdout, outdir)
                if job.stderr:
                    shutil.copy2(job.stderr, outdir)
    if die:
        raise Exception('autodiff failure, aborting')

def autodiff(job,args):
    '''compare an output file to a matching output file from a previous run of iproc.
        Returns true IFF autodiff_die is set, and there is a diff.''' 
    newDir,oldDir= args.autodiff
    diff_exists = False
    differing_files=[]
    for outfile in job.outfiles:
        oldfile = outfile.replace(newDir,oldDir)
        newfile = outfile # just for convenience
        if newfile[-6:] == 'nii.gz': 
            current_diff = nifti_diff(oldfile,newfile)
            if current_diff:
                differing_files.append(f'niftidiff {oldfile} {newfile}')
            diff_exists = current_diff or diff_exists
    return diff_exists

def nifti_diff(oldfile,newfile):
    '''take in two files, return "true" if diff exists'''
    def run_slurm(mem_in_kb,oldfile,newfile):
        slurm_mem = f'{mem_in_kb}KB'
        srun_cmd = ['srun','--partition', 'ncf', '--time', '0-0:10', '--mem', slurm_mem,'niftidiff', oldfile, newfile]
        output = commons.capture_err(srun_cmd)
        return output 

    def scale_memory(size):
        scaling_factor = 10 # guesstimate of how much memory niftidiff uses
        mem_in_kb = size * scaling_factor
        max_mem = 190000 
        if mem_in_kb > max_mem:
            mem_in_kb = max_mem
        return mem_in_kb

    if not os.path.exists(oldfile):
        logger.debug(f'oldfile DOES NOT EXIST: {oldfile}')
        return False 
         
    output = commons.capture_err(['niftidiff', oldfile, newfile])
    if output.returncode == 0:
        logger.debug(f'SAME for {newfile}') 
        return False

    else:
        # possibly, ran out of memory on local machine. For now will assume I'm on slurm, since only developer will use this

        # compute size to request
        du_query = commons.check_output(['du', oldfile])
        size = int(du_query.split()[0])
        mem_in_kb = scale_memory(size)
        output = run_slurm(mem_in_kb,oldfile,newfile)
        if output.returncode == 0:
            logger.debug('Had to srun, but came out clean') 
            return False
        elif 'Out Of Memory' in output.stderr.decode() or 'Out Of Memory' in output.stdout.decode():
            logger.debug('Out Of Memory srun error, rerunning with double')
            double_size = size * 2
            mem_in_kb = scale_memory(double_size)
            output = run_slurm(mem_in_kb,oldfile,newfile)
            return False
        else:
            logger.debug(output.args)
            for outline in output.stdout.decode().split('\n'):
                logger.debug(outline)
            for errline in output.stderr.decode().split('\n'):
                logger.debug(errline)
    # if we made it this far, there is a difference
    logger.debug(f'DIFFERENCE for {newfile}') 
    diffFile = newfile + '.diff'
    with open(diffFile,'wb') as f:
        f.write(output.stdout)
    return True

def rmfiles_from_job_specs(l):
    # takes in a list of JobSpecs, returns flat list or rmfiles.
    rmfile_list = []
    for job in l:
        for dependent_job,_ in afterok_jobs(job):
            if dependent_job.rmfiles:
                logger.debug(dependent_job.rmfiles)
                rmfile_list += dependent_job.rmfiles

        if job.rmfiles:
            logger.debug(job.rmfiles)
            for item in job.rmfiles:
                rmfile_list.append(item)
    return rmfile_list

def kwargs_prep(kwargs,args):
    try:
        assert(kwargs['partition'])
    except KeyError: #set default
        kwargs['partition'] = args.queue
    if args.nodelist:
        kwargs['nodelist'] = args.nodelist
    if args.exclude:
        kwargs['exclude'] = args.exclude
    if 'throttle' in kwargs:
        del kwargs['throttle']
 
def get_glob(args,merge_glob):
    globfiles_tomerge = glob.glob(merge_glob)
    if not globfiles_tomerge:
        logger.error(f'failed glob {merge_glob}')
        if not args.dry_run:
            raise IOError(f'failed glob {merge_glob}')
    return globfiles_tomerge

def get_glob_or(args,merge_glob1,merge_glob2):
    globfiles_tomerge1 = glob.glob(merge_glob1)
    globfiles_tomerge2 = glob.glob(merge_glob2)
    print(merge_glob1)
    print(merge_glob2)
    print(globfiles_tomerge1)
    print(globfiles_tomerge2)
    if not (globfiles_tomerge1 or globfiles_tomerge2):
        logger.error(f'failed glob {merge_glob}')
        if not args.dry_run:
            raise IOError(f'failed glob {merge_glob}')
    else:
        if globfiles_tomerge1:
            globfiles_tomerge = globfiles_tomerge1
        else:
            globfiles_tomerge = globfiles_tomerge2
    return globfiles_tomerge

def configure_logging(level):

    logdir = conf.iproc.logdir
    if not os.path.exists(logdir):
        os.makedirs(logdir)
    time.sleep(1)
    now = dt.datetime.now().strftime('%y%b%d_%H%M%S')
    log_fname = f'iproc_{conf.iproc.sub}_{conf.template.midvol_sess}_{now}.log'
    log_path = os.path.join(logdir, log_fname)

    log_format = '[%(asctime)s][%(levelname)s] - %(name)s - %(message)s'

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'console': {
                'format': log_format
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'console',
            },
            'file': {
                'class': 'logging.FileHandler',
                'formatter': 'console',
                'filename': log_path
            },
        },
        'loggers': {
        # root logger
            '': {
                'level': level,
                'handlers': ['console', 'file'],
            },
        },
    })
    return log_path

def log_provenance(conf_filename,log_path):
    #git_repo = os.path.join(conf.iproc.CODEDIR, '.git')
    #cmd = [
    #    'git',
    #    '--git-dir', git_repo,
    #    'rev-parse', 'HEAD'
    #]
    #commit_hash = commons.check_output(cmd).strip()
    #logger.info(commons.program(sys.argv))
    #logger.info(commons.machine())
    #logger.info(commons.check_output(['module list'],shell=True))
    #logger.info('git checksum: {}'.format(commit_hash))
    #ogger.info('conf filename: {}'.format(os.path.abspath(conf_filename)))
    #logger.info(list(conf.items()))
    logger.info(f'logfile: {log_path}')


phraseList=[
    ('setup',setup),
    ('bet',check_bet),
    ('unwarp_motioncorrect_align',unwarp_motioncorrect_align),
    ('T1_warp_and_mask',T1_warp_and_mask),
    ('combine_and_apply_warp',combine_and_apply_warp),
    ('filter_and_project',filter_and_project)
]
stages = collections.OrderedDict(phraseList)

def main():
    # define args
    parser = ap.ArgumentParser(usage='%(prog)s -c <configfile> -s {setup,bet,unwarp_motioncorrect_align,T1_warp_and_mask,combine_and_apply_warp,filter_and_project} \n %(prog)s -h for full option listing')

    # global/universal args
    required = parser.add_argument_group('REQUIRED')
    required.add_argument('-c', '--config-file', required=True,
        help='Subject configuration file')
    required.add_argument('-s', '--stage', required=True,
        help='stage of analysis to carry out', choices=list(stages.keys()) )
    parser.add_argument('--debug', action='store_true',
        help='Enable debug messages')
    parser.add_argument('--executor', choices=('local', 'slurm', 'pbsubmit'),
        default='slurm')

    job_handling = parser.add_argument_group('job handling behavior options')
    job_handling.add_argument('--no-remove-files', action='store_true',
        help='generate shell script of files to remove, rather than the default, which is to automatically remove files at the earliest opportunity.')
    job_handling.add_argument('--overwrite', action='store_true',
        help='overwrite files from prior runs. Default is to skip reruns of jobs that have already produced output files.')

    ## edge case handlers
    parser.add_argument('--blank-rmfiles', action='store_true',
        help='if no rmfiles dump is found from a prior step, ignore and load blank. You should only need to use this if you see some error mentioning rmfiles.')

    ## alternate use cases
    parser.add_argument('--bids',
        help='instead of downloading from XNAT, download from specified BIDS directory')
    parser.add_argument('--autodiff', nargs=2, metavar = ('<dirNew>','<dirOld>'),
        help='*EXPERIMENTAL* compare .nii.gz files produced in new dir to files produced in old dir. Uses niftidiff.')
    parser.add_argument('--autodiff-die', action='store_true',
        help='immediately quit if any autodiff comes out finding a difference')

    ## executor modifiers
    executor = parser.add_argument_group('executor modifier options') 
    executor.add_argument('-q', '--queue', default='fasse',
        help='default slurm/pbs partition to submit to')
    executor.add_argument('-i', '--interval', default=5, type=int,
        help='check children jobs once every i minutes')
    executor.add_argument('--dry-run', action='store_true',
        help='dry-run mode (no scripts are actually run)')
    executor.add_argument('--skip-fail', action='store_true',
        help='if an individual job fails, try to finish the stage. If this is not set, behavior is to cancel all running jobs and halt')
    executor.add_argument('--single-file', action='store_true',
        help='Only run one job at a time')

    ## Mostly slurm-specific
    
    slurm = parser.add_argument_group('slurm-specific modifier options') 
    slurm.add_argument('--exclude',
        help='list of nodes to exclude from slurm run, usage --exclude "holy2a06201,holy2a06202" ')
    slurm.add_argument('--nodelist',
        help='list of nodes to run on for slurm run, usage --nodelist "holy2a06201,holy2a06202" ')
    slurm.add_argument('--sbatch-args', nargs='+', 
        help='a way to pass in arguments to sbatch, if needed.\n Will be applied to all sbatch commands.\n each argument must be a single string without spaces, and missing the initial dashes, e.g. --sbatch-args "chdir=<directory>" (which would correspond to `sbatch --chdir=<directory>` in regular command line usage of sbatch.)')

    ## wrappers
    wrappers = parser.add_argument_group('wrapper options') 
    wrappers.add_argument('--singularity',
        help='run job commands through centos6 singularity container. \n on the NCF, you should pass this /n/sw/singularity/fasrc-compute-1.0.el6.img. Should be used together with --no-srun, as srun use within singularity containers is typically problematic.')
    # TODO: implement Fra's workaround to submit srun/squeue from within the container
    wrappers.add_argument('--no-srun', action='store_true',
        help='environment is not safe to run srun. Typically only used in conjunction with singularity and slurm')
    wrappers.add_argument('--wrap',
        help='run job commands through wrapper. \n current options are profiling/du.sh, profiling/mountinfo.sh, and profiling/nfsstat_before_after.sh.')
    wrappers.add_argument('--user-wrap',
        help='run job commands through user-specified wrapper. \n Make sure to use the full path to your wrapper script.')
    wrappers.add_argument('--wrap-args', nargs='+',
        help='a way to pass in arguments to your wrapper script, if needed')
    # end of argparser spec
    ##

    # set up args
    args = parser.parse_args()
    if args.sbatch_args:
        args.sbatch_args = [f'--{arg}' for arg in args.sbatch_args]

    # parse the configuration file
    conf.parse(os.path.expanduser(args.config_file))
    # set variables with fully deterministic locations
    allowed_fmap_regimes = ['topup','fsl_prepare_fieldmap']
    if not conf.fmap.preptool in allowed_fmap_regimes:
        logger.error(f'{args.config_file} must have a fmap:preptool value matching one of {allowed_fmap_regimes}')
        exit(1)

    conf.iproc.WORKDIR = os.path.join(conf.iproc.SCRATCHDIR,str(int(time.time())))
    #commons.move_on_exit(conf.iproc.WORKDIR, conf.iproc.OUTDIR)
    # note if this is local, rather than networked scratch, this may not work
    if not os.path.isdir(conf.iproc.WORKDIR):
        os.makedirs(conf.iproc.WORKDIR)
    

    # construct outdir shortcuts
    conf.iproc.LOGDIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'logs')
    conf.iproc.QCDIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'QC')
    conf.iproc.NATDIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'NAT')
    #conf.iproc.MNI222DIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'MNI222')
    #conf.iproc.NAT222DIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'NAT222')
    conf.iproc.FS6DIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'FS6')
    conf.iproc.RMFILE_DUMP= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,'rmfiles')
    if not os.path.isdir(conf.iproc.RMFILE_DUMP):
        os.makedirs(conf.iproc.RMFILE_DUMP)

    if conf.out_atlas.RESOLUTION in ('111','222'):
        conf.iproc.MNI_RESAMP_DIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,f'MNI{conf.out_atlas.RESOLUTION}')
        conf.iproc.NAT_RESAMP_DIR= os.path.join(conf.iproc.OUTDIR,conf.iproc.SUB,f'NAT{conf.out_atlas.RESOLUTION}')
    else:
        raise Exception(f'Resampled RESOLUTION is currently set as {conf.out_atlas.RESOLUTION}, but it must be 111 or 222. Check your subject configuration file.')


    # make sure template dir exists
    template_dir = os.path.join(conf.iproc.OUTDIR, conf.iproc.SUB, 'cross_session_maps', 'templates')
    conf.template.TEMPLATE_DIR = template_dir
    if not os.path.exists(template_dir):
        os.makedirs(template_dir)

    #################################################################
    ### ----- CHANGING TO NATIVE SPACE MIDVOL!!! 2024.10.04 ----- ###
    ### --------- NOW TO UPSAMPLED 2MM SPACE!!! 2024.10.05 ------ ###
    #################################################################

    if conf.out_atlas.RESOLUTION == '111':
        conf.template.midvols_mean = os.path.join(conf.template.TEMPLATE_DIR,f'{conf.iproc.SUB}midmean_midvols_on_midvoltarg.nii.gz')
    elif conf.out_atlas.RESOLUTION == '222':
        conf.template.midvols_mean = os.path.join(conf.template.TEMPLATE_DIR,f'{conf.iproc.SUB}_midvol_unwarp_2mm.nii.gz')


    # get path to current iProc software
    try:
        _ = conf.iproc.CODEDIR
    except ConfigError:
        # DEVIATION (see NOTICE.md): runtime assets (runscript/, configs/, wrappers/,
        # modwrap.sh, mni_masks/, iProc_p4_sbatch_combined.py) are vendored INTO the
        # package dir (one level above cli/), so CODEDIR resolves there — not cli/.
        conf.iproc.CODEDIR = str(Path(__file__).resolve().parent.parent)

    # set freesurfer ${SUBJECTS_DIR} env var
    os.environ['SUBJECTS_DIR'] = conf.fs.SUBJECTS_DIR
    # specific to slurm environments
    if args.no_srun or args.executor != 'slurm':
        os.environ['IPROC_SRUN'] = "NO"
    else:
        os.environ['IPROC_SRUN'] = "YES"

    # configure logging
    level = logging.DEBUG if args.debug else logging.INFO
    log_path = configure_logging(level)
    # log provenance for this program
    log_provenance(args.config_file, log_path)

    # open and parse CSVs
    scans = csvHandler.scansHandler(conf)
    scans.ingest_task_csv(conf.csv.TASKTYPELIST)
    
    scans.ingest_bold_csv(conf.csv.SCANLIST)
    midvol_boldno = int(conf.template.MIDVOL_BOLDNO)

    # gross but prevents errors caused by user typos
    conf.template.MIDVOL_BOLDNAME = scans.scan_by_session[conf.template.MIDVOL_SESS].bold_scans[midvol_boldno]['TYPE']
    
    args.cluster = {}
    csvHandler.load_cluster_requests(conf.csv.CLUSTER_REQUESTS,args)
    
    # copy CSVs to log directory so we have permanent record
    csv_archive = log_path.rstrip('log') + 'csv_cfg_archive'
    # exist_ok: concurrent iproc invocations sharing a subject+session+minute
    # timestamp (e.g. a per-run SLURM array fanning out one stage) would
    # otherwise collide here with FileExistsError; the archived cfg/scanlist
    # copies are per-invocation-named, so sharing the dir is harmless.
    os.makedirs(csv_archive, exist_ok=True)
    shutil.copy2(conf.csv.TASKTYPELIST,csv_archive)
    shutil.copy2(conf.csv.SCANLIST,csv_archive)
    shutil.copy2(conf.csv.CLUSTER_REQUESTS,csv_archive)
    shutil.copy2(args.config_file,csv_archive)

    if args.bids:
        # add 'BIDS_ID' attribute
        bids.match_scan_no_to_bids(args.bids,scans)

    # run the stage specified by the user
    steps = iProcSteps.jobConstructor(conf,scans,args)
    stage = stages.get(args.stage)
    
    rm_list = stage(steps,args)

    rmscript_location = os.path.join(conf.iproc.LOGDIR,f'rm_{args.stage}.sh')
    rm_script = commons.ScriptBuilder(rmscript_location)
    rm_script.check_header()
    for rmfile in rm_list:
        rm_script.append(['rm','-rf', rmfile])
    logger.info(f'in order to remove files, run {rmscript_location}')

if __name__ == '__main__':
    main()
