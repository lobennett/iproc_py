#!/usr/bin/env python
import csv
import logging
import re
'''
contains info from scanlist csv and provides iterator access
'''

#should get logger from calling script
logger = logging.getLogger(__name__)

class scansHandler(object):
    '''
    holds all scan information for an analysis session in a structured format
    that can be accessed by scan type and session
    '''
    def __init__(self,conf):
        self.scan_by_session = {}
        # for use by _io_file_fmt in a jobConstructor
        self.sessionid = None
        self.scan_no = None
        self.scan_name = None
        self.sess = None
        self.task_dict = {} 
        self.csv_errors = {}
        self.conf = conf

    def reset_default_sessionid(self):
        self.sessionid = None
        self.scan_no = None
        self.scan_name = None
        self.sess = None
       
    ## not going to ingest task csv, leave that as it is for now
    def ingest_bold_csv(self, csv_fname):
        # open reader
        if not self.task_dict:
            raise Exception('you must ingest_task_csv before you ingest_bold_csv')
        
        with open(csv_fname, newline=None) as f:
            self.csv_errors[csv_fname]=[]
            reader = csv.DictReader(f)
            # Analyze is categorically different from the other variables
            schema = ['SUBJID','SESSION_ID','Analyze','BLD','TYPE','ANAT','FMAP_MAG','FMAP_PHASE','FMAP_AP','FMAP_PA', 'T2', 'T2_SESSION_ID']
            BOM = '\xef\xbb\xbf' #Excel UTF-8 Byte Order mark munge
            if BOM in reader.fieldnames[0]:
                logger.debug('automatically stripping BOM')
                reader.fieldnames[0] = reader.fieldnames[0].strip(BOM)
            if not schema == reader.fieldnames:
                raise KeyError('column labels of "{}" do not conform to schema {}'.format(csv_fname,','.join(schema)))
            bold_scans = []
            fmap_scans = []
            anat_scans = []
            for scan in reader:
                if 'ANAT' in scan['TYPE']:
                    anat_scans.append(scan)
                elif 'FMAP' in scan['TYPE']:
                    fmap_scans.append(scan)
                else: #is bold scan
                    bold_scans.append(scan)

            ordered_scans = anat_scans + fmap_scans + bold_scans
            for scan in ordered_scans:
                logger.debug(scan)
                if not int(scan['Analyze']):
                    # don't process
                    continue
                # make sure values are formatted properly
                word_with_dash = r'[\w]+\Z'
                try:
                    if not re.match(word_with_dash,scan['SUBJID']):
                        self.csv_errors[csv_fname].append('SUBJID "{}" has illegal characters'.format(scan['SUBJID']))
                    if not re.match(word_with_dash,scan['SESSION_ID']):
                        self.csv_errors[csv_fname].append('SESSION_ID "{}" has illegal characters'.format(scan['SESSION_ID']))
                    if not re.match(r'[0-1]+\Z',scan['Analyze']):# bool
                        self.csv_errors[csv_fname].append('Analyze "{}" has illegal characters'.format(scan['Analyze']))
                    if not re.match(r'[0-9]+\Z',scan['BLD']):#integer
                        self.csv_errors[csv_fname].append('BLD "{}" has illegal characters'.format(scan['BLD']))
                    if not re.match(r'[a-zA-Z0-9_]+\Z',scan['TYPE']):#string
                        self.csv_errors[csv_fname].append('TYPE "{}" has illegal characters'.format(scan['TYPE']))
                    if not re.match(r'[0-9]+\Z',scan['ANAT']):#integer
                        self.csv_errors[csv_fname].append('ANAT "{}" has illegal characters'.format(scan['ANAT']))
                    if not re.match(r'[0-9]+\Z',scan['FMAP_MAG']):#integer 
                        self.csv_errors[csv_fname].append('FMAP_MAG "{}" has illegal characters'.format(scan['FMAP_MAG']))
                    if not re.match(r'[0-9]+\Z',scan['FMAP_PHASE']):#integer
                        self.csv_errors[csv_fname].append('FMAP_PHASE "{}" has illegal characters'.format(scan['FMAP_PHASE']))
                    if not re.match(r'[0-9]+\Z',scan['FMAP_AP']):#integer 
                        self.csv_errors[csv_fname].append('FMAP_AP"{}" has illegal characters'.format(scan['FMAP_AP']))
                    if not re.match(r'[0-9]+\Z',scan['FMAP_PA']):#integer
                        self.csv_errors[csv_fname].append('FMAP_PA"{}" has illegal characters'.format(scan['FMAP_PA']))
                    if not re.match(r'[0-9]+\Z',scan['T2']):#integer
                        self.csv_errors[csv_fname].append('T2"{}" has illegal characters'.format(scan['T2']))
                except TypeError:
                    logger.error('type error on regex, probably means that one of the lines in the CSV is missing some values, i.e. is too short')
                    logger.error('check {}'.format(csv_fname))
                    raise

                sessid = scan['SESSION_ID']
                # add scan to list of scans from that session
                if sessid in self.scan_by_session:
                    try:
                        self.scan_by_session[sessid].append_scan(scan)
                    except Exception as e :
                        logger.error('problem with file {}'.format(csv_fname))
                        # so the stack trace is more informative
                        self.scan_by_session[sessid].append_scan(scan)
                        raise e
                else:
                    new_session = session()
                    try:
                        new_session.append_scan(scan)
                    except Exception as e :
                        logger.error('problem with file {}'.format(csv_fname))
                        raise e
                    self.scan_by_session[sessid] = new_session
            # check to make sure that all the TYPE values from scanlist
            # match some row in tasklist 
            for sess in list(self.scan_by_session.values()):
                if sess.sessid == self.conf.template.MIDVOL_SESS:
                    stripped_midvol_no = int(self.conf.template.MIDVOL_BOLDNO)
                    if stripped_midvol_no not in sess.bold_scans:
                        self.csv_errors[csv_fname].append('Midvol scan {} not found in bold_scans for midvol session {}. Make sure the "Analyze" value is set to 1'.format(stripped_midvol_no,sess.sessid))
                types = [bold_scan['TYPE'] for bold_scan in list(sess.bold_scans.values())]
                for task_type in types:
                    if task_type not in self.task_dict:
                        self.csv_errors[csv_fname].append('"{}" does not have a corresponding row in the task CSV'.format(task_type))
            compile_csv_error_report(self.csv_errors)

    def ingest_task_csv(self, csv_fname):
        # open reader
        with open(csv_fname, newline=None) as f:
            self.csv_errors[csv_fname]=[]
            reader = csv.DictReader(f)
            schema=['TYPE','TR','SKIP','SMOOTHING','NUMVOL','NUMECHOS']
            if not schema == reader.fieldnames:
                raise KeyError('column labels of {} do not conform to schema {}'.format(csv_fname,','.join(schema)))
            for d in reader:
                # check for correct value formatting
                if not re.match(r'[a-zA-Z0-9_]+\Z',d['TYPE']):
                    self.csv_errors[csv_fname].append('TYPE "{}" has illegal characters'.format(d['TYPE']))
                if not re.match(r'[0-9]+\.?[0-9]*\Z',d['TR']): #any number
                    self.csv_errors[csv_fname].append('TR "{}" has illegal characters'.format(d['TR']))
                if not re.match(r'[0-9]+\Z',d['SKIP']):#integer
                    self.csv_errors[csv_fname].append('SKIP "{}" has illegal characters'.format(d['SKIP']))
                if not re.match(r'[0-9.]+\Z',d['SMOOTHING']):
                    self.csv_errors[csv_fname].append('SMOOTHING "{}" has illegal characters'.format(d['SMOOTHING']))
                if not re.match(r'[0-9]+\Z',d['NUMVOL']):
                    self.csv_errors[csv_fname].append('NUMVOL "{}" has illegal characters'.format(d['NUMVOL']))
                if not re.match(r'[0-9]+\Z',d['NUMECHOS']):
                    self.csv_errors[csv_fname].append('NUMECHOS "{}" has illegal characters'.format(d['NUMVOL']))
                self.task_dict[d['TYPE']] = d
    def session_names(self):
        return list(self.scan_by_session.keys())
    def sessions(self):
        return self._sessions_screened('bold')
    def anat_sessions(self):
        return self._sessions_screened('anat')
    def _sessions_screened(self,screendict):
        for sessionid, sess in list(self.scan_by_session.items()):
            screendict_translate = {'anat':list(sess.anat_scans.values()),
                                    'bold':list(sess.bold_scans.values())}
            value_check = screendict_translate[screendict]
            if not any(value_check):
                continue 
            self.sessionid = sessionid
            self.sess = self.scan_by_session[self.sessionid]
            yield (sessionid, sess)
    def tasks(self):
        # should only be used within a sessions block
        # want to sort bold scans by their acquisition number
        for bold_scan in sorted(list(self.sess.bold_scans.values()),key=lambda s:int(s['BLD'])):
            self.scan_no = bold_scan['BLD']
            task_type = bold_scan['TYPE']
            self.scan_name = task_type
            yield (task_type, bold_scan)
    def fieldmaps(self):
        # want to return fmap scans in order of increasing aquisition number
        for fmap_scan in sorted(list(self.sess.fmap_scans.values()),key=lambda s:int(s['FIRST_FMAP'])):
            #this was done to grandfather in fmap_phase from when it was fmap_phase
            self.scan_no = fmap_scan['SECOND_FMAP']
            fmap_dir = fmap_scan['DIR']
            self.scan_name = fmap_dir
            yield (fmap_dir,fmap_scan)
    def anats(self):
        for anat_scan in list(self.sess.anat_scans.values()):
            self.scan_no = anat_scan['ANAT']
            anat_dir = anat_scan['DIR']
            self.scan_name = anat_dir
            yield (anat_dir,anat_scan)
    def set_sessid(self,sessionid):
        self.sessionid = sessionid
    def set_name(self,name):
        self.scan_name = name
    def set_task_type(self,task_type):
        raise NotImplementedError
    def set_midvol(self,conf):
        # sets class members to midvol from config
        self.sessionid = conf.template.MIDVOL_SESS 
        self.sess = self.scan_by_session[self.sessionid]
        self.scan_no = conf.template.MIDVOL_BOLDNO
        self.scan_name = conf.template.MIDVOL_BOLDNAME
    def set_anat(self,sessionid,scan_no):
        # sets class members to T1_sess from config
        # will probably have to differentiate from MNI etc at some point.
        self.sessionid = sessionid
        self.sess = self.scan_by_session[self.sessionid]
        self.scan_no = scan_no
        self.scan_name = 'NAT'

class session:
    def __init__(self):
        self.bold_scans = {}
        self.fmap_scans = {}
        self.anat_scans = {}
        self.subjid = None
        self.sessid = None
        self.fmap_prep_type = None

    def append_scan(self, scan):
        if not self.subjid:
            self.subjid = scan['SUBJID']   
        else:
            #subjid should match for all scans in the same session
            if not scan['SUBJID'] == self.subjid:
                logger.error(scan)
                raise ValueError('SUBJID should match for all scans in the same session')
        if not self.sessid:
            self.sessid = scan['SESSION_ID']   
        else:
            #sessid should match for all scans in the same session
            if not scan['SESSION_ID'] == self.sessid:
                logger.error(scan)
                raise ValueError('SESSION_ID should match for all scans in the same session')
        # add scan to appropriate dict
        if 'ANAT' in scan['TYPE']:
            # scan is an anat scan
            anat_no = scan['ANAT']
            if anat_no in self.anat_scans:
                dup = 'duplicate entry: {SUBJID},{SESSION_ID},1,{SCAN}'.format(
                    SUBJID=self.subjid,SESSION_ID=self.sessid,SCAN=anat_no)
                raise ValueError(dup)
            else:
                scan['DIR']=scan['TYPE']
                self.anat_scans[anat_no]=scan
            logger.debug('added {}:{} to anat_scans'.format(anat_no,scan))
        elif 'FMAP' in scan['TYPE']:
            # scan is a field map scan
            fmap_prep_type,first_fmap,second_fmap = self._fmap_format_check(scan)

            scan['FMAP_PREP_TYPE'] = fmap_prep_type
            # these two are done so that we can do sorting in a preptype-agnostic way
            if (first_fmap,second_fmap) in self.fmap_scans:
                dup = 'duplicate entry: {SUBJID},{SESSION_ID},1,{SCAN}'.format(
                    SUBJID=self.subjid,SESSION_ID=self.sessid,SCAN=(first_fmap,second_fmap))
                raise ValueError(dup)
            else:
                scan['DIR'] = scan['TYPE']
                self.fmap_scans[(first_fmap,second_fmap)] = scan
            logger.debug('added {}:{} to fmap_scans'.format((first_fmap,second_fmap),scan))

        else:
            # Bold scan
            # check for duplicate scan numbers
            bold_no = int(scan['BLD'])
            if bold_no in self.bold_scans:
                dup = 'duplicate entry: {SUBJID},{SESSION_ID},1,{BLD}'.format(
                    SUBJID=self.subjid,SESSION_ID=self.sessid,BLD=bold_no)
                raise ValueError(dup)
            bold_types = [s['TYPE'] for s in list(self.bold_scans.values())]
            if scan['TYPE'] in bold_types:
                logger.warn(scan)
                dup = 'assigning bold scan {} to a type {} that already has assigned bold scans'.format(bold_no,scan['TYPE'])
                logger.warn(dup)
            # scan is a bold scan
            bold_scan = scan
            self.bold_scans[bold_no] = scan
            logger.debug('added {} to bold_scans'.format(bold_no))

            ## check entry ANAT value for consistency 
            try:
                bold_scan['ANAT_DIR'] = self.anat_scans[bold_scan['ANAT']]['DIR']
            except KeyError:
                logger.warning('no such anat found! {}'.format(bold_scan))
                logger.warning('{}'.format(self.anat_scans))
                bold_scan['ANAT_DIR'] = 'No Anat For Session in CSV'

            ## Check Fmap values
            fmap_prep_type,first_fmap,second_fmap = self._fmap_format_check(scan)
            try:
                fmap_scan = self.fmap_scans[(first_fmap,second_fmap)]
                bold_scan['FMAP_DIR'] = fmap_scan['DIR']
            except KeyError:
                logger.error('no such fmap found! {}'.format(bold_scan))
                raise
            # make sure fmap scan is correct format
            if fmap_prep_type != fmap_scan['FMAP_PREP_TYPE']:
                raise ValueError('BLD "{}" has FMAP of format {}, unlike FMAP {},{} in the same session, {}. \n iproc only supports one fmap prep type per subject. \n Please move the fmap scan numbers to the correct column in the bold scan row'.format(bold_no,fmap_prep_type,first_fmap,second_fmap,self.sessid))

    def _fmap_format_check(self,scan):
        ''' helper function to check fmap values makes sense '''

        fmap_mag_no = int(scan['FMAP_MAG'])
        fmap_phase_no = int(scan['FMAP_PHASE'])
        fmap_AP_no = int(scan['FMAP_AP'])
        fmap_PA_no = int(scan['FMAP_PA'])

        if fmap_mag_no == 0 and fmap_phase_no == 0:
            # we're in AP PA mode
            if fmap_AP_no == 0 or fmap_PA_no == 0:
                raise ValueError('fmap columns are all zero! Please set values for either APPA or double echo style (Mag/Phase) style images')
            # for later
            fmap_prep_type = 'topup'
            first_fmap = fmap_AP_no 
            second_fmap = fmap_PA_no
        elif fmap_AP_no == 0 and fmap_PA_no == 0:
            if fmap_mag_no == 0 or fmap_phase_no == 0:
                raise ValueError('fmap columns are all zero! Please set values for either APPA or double echo style (Mag/Phase) style images')
            fmap_phase_diff = fmap_phase_no - fmap_mag_no
            if fmap_phase_diff != 1 and fmap_phase_diff != 2:
               raise NotImplementedError('FMAP_PHASE {FMAP_PHASE} is not one scan behind FMAP_MAG {FMAP_MAG} for a FMAP scan from {SESSID}. This is not normal for scans collected at Harvard CBS.'.format(
            FMAP_PHASE=fmap_phase_no,FMAP_MAG=fmap_mag_no,SESSID=self.sessid))
            # for later
            fmap_prep_type = 'fsl_prepare_fieldmap'
            first_fmap = str(fmap_mag_no)
            second_fmap = str(fmap_phase_no)
        else:
            raise ValueError('Invalid fmap values. Please set values for either APPA or double echo style (Mag/Phase) style images\n{}'.format(scan))

        scan['FIRST_FMAP'] = first_fmap 
        scan['SECOND_FMAP'] = second_fmap 
        return (fmap_prep_type,first_fmap,second_fmap)

def load_cluster_requests(csv_fname,args):
    ''' takes in the name of a cluster requests csv, loads the information 
    into the args object. '''
    csv_errors = {}
    with open(csv_fname, newline=None) as f:
        reader = csv.DictReader(f)
        schema=['STEP','RUNMODE','partition','time','mem','cpu']
        if not schema == reader.fieldnames:
            raise KeyError('column labels of "{}" do not conform to schema {}'.format(csv_fname,','.join(schema)))
        csv_errors[csv_fname]=[]
        for step in reader:
            cluster_args = {k:v for k,v in list(step.items()) if k != 'STEP'}
            to_pop = []
            for k,v in list(cluster_args.items()):
                if v == 'default' :
                    # remove from cluster_args, implicitly selecting default from
                    #the executor 
                    to_pop.append(k)
                    continue
                # format checking
                #STEP is an arbitrary string, no checking advisable.
                #partition is up to the cluster admin, no checking advisable
                #time is, again, up to the cluster admin and executor. no checking advisable.
                #mem is up to the executor. 
                #I can be fairly confident what the CPU argument is going to look like.
                if k == 'cpu': #if this was default, that has already been dealt with
                    if not re.match(r'[0-9]+\Z',v):#integer
                        csv_errors[csv_fname].append('cpu entry "{}" has illegal characters'.format(v))
            for k in to_pop:
                cluster_args.pop(k)
            args.cluster[step['STEP']] = cluster_args
    compile_csv_error_report(csv_errors)

def compile_csv_error_report(csv_errors):
    #takes in csv_errors, which should be a dictionary of csv_filename:[] pairs.
    # if the error lists are empty, returns. Otherwise, prints errors to log
    # and raises an exception
    if any(csv_errors.values()):
        for csv,errorlist in list(csv_errors.items()):
            if not errorlist:
                continue
            logger.debug('{} has the following errors'.format(csv))
            for error in errorlist:
                logger.debug(error)
        raise Exception('CSVs have errors, see above')

if __name__ == "__main__":
    s = scansHandler() 
    #TODO: define tests here
