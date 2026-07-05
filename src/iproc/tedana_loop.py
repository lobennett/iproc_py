import glob
import subprocess

### ------ EDIT HERE ------- ###
sub='1AB23' # Participant ID
mri_data_dir = '/path/to/mri_data_AP' # Full path to mri_data, mri_dat_AP or mri_data_PA
resolution = '222' # mm resolution: either 111 or 222, as a string
partition = 'fasse_bigmem'
### ------------------------ ###
for space in ['NAT','MNI']:
	if (space == 'NAT'):
		runs = glob.glob(f'{mri_data_dir}/{sub}/{space}{resolution}/*_{sub}/*/*_unwarp_anat_e1.nii.gz')
	elif (space == 'MNI'):
		runs = glob.glob(f'{mri_data_dir}/{sub}/{space}{resolution}/*_{sub}/*/*_unwarp_anat_mni_e1.nii.gz')


	for run_str in runs:
		tmp = run_str.replace(f'{mri_data_dir}/{sub}/{space}{resolution}/','')
		pieces = tmp.split('/')
		ses = pieces[0]
		fullrun = pieces[1]
		temp2 = fullrun.split('_')
		task = temp2[0]
		run = temp2[1]

		command_params = f'python run_tedana.py --sub {sub} --ses {ses} --task {task} --run {run} --mridatadir {mri_data_dir} --outname tedana --space {space} --resolution {resolution}'
		command = f'sbatch -p {partition} -n 1 -t 10:00:00 --mem 450G -o tedana_%J.out -e tedana_%J.err --wrap "{command_params}"'
		print(command)

		proc= subprocess.Popen([f'{command}'] ,stdout=subprocess.PIPE,shell=True)
		(out_ted,err_ted) = proc.communicate()

		print(str(out_ted.strip(),'UTF-8'))
		if err_ted != None:
			print("tedana error",err_ted)    
