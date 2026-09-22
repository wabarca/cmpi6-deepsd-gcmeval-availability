#!/bin/bash
model_types="historical ssp126 ssp245 ssp370 ssp585" 
variables="pr psl tas tasmax tasmin zg"
samplegrid=$HOME/Scripts/samplegrid.nc
#================================================================================
# 1. Clip netcdf files to working region
#================================================================================
# lat_up=43
# lat_down=-18.5
# lon_left=-120
# lon_right=-40.5
# for model in $(ls); do
#     if [ -d "$model" ]; then
#         cd $model
#             echo "Processing model:" $model
#             echo "Working in " $(pwd)
#             mkdir -p $HOME/CMIP6_GCMs_Remaped/${model}
#             remaped_models=$HOME/CMIP6_GCMs_Remaped/${model}
#             files=(*)
#             filename=$(echo "${files[0]}")
#             realization=$(echo $filename | cut -d "_" -f 4)
#             echo "Realization: " $realization
#             for file in $(ls); do
#                 # echo "Remapping file:" $file
#                 # cdo -P 8 -s remapbil,${samplegrid} ${file} ${file%.*}_remap.nc 
#                 # echo "Regriding:" ${file%.*}_remap.nc
#                 cdo -P 8 sellonlatbox,${lon_left},${lon_right},${lat_down},${lat_up} ${file%.*}.nc ${file%.*}_remap.nc
#                 # rm ${file%.*}_remap.nc
#                 mv ${file%.*}_remap.nc ${remaped_models}/${file}
#             done
#             # rm *
#         cd ..
#     fi
# done
# #================================================================================
# 2. Merging times
#================================================================================
# for model in $(ls); do
#     if [ -d "$model" ]; then
#         cd $model
#             echo "Processing model:" $model
#             echo "Working in " $(pwd) 
#             mkdir -p $HOME/CMIP6_GCMs_Merged/${model}
#             merged_models=$HOME/CMIP6_GCMs_Merged/${model}
#             files=(*)
#             filename=$(echo "${files[0]}")
#             realization=$(echo $filename | cut -d "_" -f 5)
#             for model_type in $model_types; do
#                 echo "Processing:" $model_type
#                 for variable in $variables; do
#                     echo "Processing:" $variable
#                     echo "Processing files:" ${variable}_${model}_${model_type}_${realization}
#                     if [ "${model_type}" == "historical" ]; then
#                         cdo -P 8 mergetime "${variable}_day_${model}_${model_type}_${realization}_*" "${variable}_${model}_${model_type}_${realization}_19500101-20141231.nc"
#                         mv ${variable}_${model}_${model_type}_${realization}_19500101-20141231.nc ${merged_models}
#                         # cdo -P 8 mergetime "${variable}_Amon_${model}_${model_type}_${realization}_*" "${variable}_${model}_${model_type}_${realization}_19500101-20141231.nc"
#                         # mv ${variable}_${model}_${model_type}_${realization}_19500101-20141231.nc ${merged_models}
#                         # echo ${variable}_${model}_${model_type}
#                     else
#                         cdo -P 8 mergetime "${variable}_day_${model}_${model_type}_${realization}_*" "${variable}_${model}_${model_type}_${realization}_20150101-21001231.nc"
#                         mv "${variable}_${model}_${model_type}_${realization}_20150101-21001231.nc" ${merged_models}
#                         # cdo -P 8 mergetime "${variable}_Amon_${model}_${model_type}_${realization}_*" "${variable}_${model}_${model_type}_${realization}_20150101-21001231.nc"
#                         # mv "${variable}_${model}_${model_type}_${realization}_20150101-21001231.nc" ${merged_models}
#                     fi
#                     echo "Done!"
#                 done
#             done
#         cd ..
#     fi
# done
#================================================================================
# 3. Selecting correct dates in files
#================================================================================
# for model in $(ls); do
#     if [ -d "$model" ]; then
#         cd $model
#             echo "Processing model:" $model
#             echo "Working in " $(pwd)
#             mkdir -p $HOME/CMIP6_GCMs_Merged/${model}
#             merged_models=$HOME/CMIP6_GCMs_Merged/${model}
#             mkdir -p $HOME/CMIP6_GCMs_Remaped/${model}
#             remaped_models=$HOME/CMIP6_GCMs_Remaped/${model}
#             mkdir -p $HOME/CMIP6_GCMs_Corrected/${model}
#             corrected_models=$HOME/CMIP6_GCMs_Corrected/${model}
#             # files=(*)
#             # filename=$(echo "${files[0]}")
#             # realization=$(echo $filename | cut -d "_" -f 4)
#             for file in $(ls); do
#                 echo "Processing file: " $file
#                 scenario=$(echo $file | cut -d "_" -f 3)
#                 echo "Processing scenario: " $scenario
#                 cal=`cdo sinfon $file | grep -o -P 'Calendar.{0,24}'`
#                 if [[ ${scenario} == "historical" ]];
#                     then 
#                         if [[ ${cal} == *"gregorian"* ]];
#                             then
#                             nd="23741"
#                             else
#                             nd="23725" 
#                         fi
#                     else
#                         if [[ ${cal} == *"gregorian"* ]];
#                             then
#                             nd="31411"
#                             else    
#                             nd="31390"
#                         fi
#                 fi 
#                 echo "Number of days: " $nd
#                 days=$(echo `cdo ntime $file` | cut -d " " -f 1)
#                 echo "Total days: " $days
#                 if [[ "${days}" -ge "${nd}" ]];
#                     then 
#                     echo ""
#                     echo "*************************************************************"
#                     echo "ERROR: el fichero no tiene el numero de dias correcto"
#                     echo "*************************************************************"
#                     echo ""
#                     if [[ "${days}" -ge "${nd}" ]];
#                     then
#                         if [[ ${scenario} == "historical" ]];
#                             then
#                             echo "Numero de dias mayor de lo esperado. Selecciono 1950-2014"
#                             cdo selyear,1950/2014 $file ${file%.*}_corrected.nc
#                             mv ${file%.*}_corrected.nc ${corrected_models}/${file}
#                             else
#                             echo "Numero de dias mayor de lo esperado. Selecciono 2015-2100"
#                             cdo selyear,2015/2100 $file ${file%.*}_corrected.nc
#                             mv ${file%.*}_corrected.nc ${corrected_models}/${file}
#                         fi
#                     else
#                     echo "Numero de dias menor de lo esperado. Exit (REVISAR GCM)"
#                     exit 1
#                     fi
#                 fi
#             done
#         cd ..
#     fi
# done
#================================================================================
# 4. Regridding netcdf files
#================================================================================
for model in $(ls); do
    if [ -d "$model" ]; then
        cd $model
            echo "Processing model:" $model
            echo "Working in " $(pwd)
            mkdir -p $HOME/CMIP6_GCMs_Merged/${model}
            merged_models=$HOME/CMIP6_GCMs_Merged/${model}
            mkdir -p $HOME/CMIP6_GCMs_Remaped/${model}
            remaped_models=$HOME/CMIP6_GCMs_Remaped/${model}
            mkdir -p $HOME/CMIP6_GCMs_Corrected/${model}
            corrected_models=$HOME/CMIP6_GCMs_Corrected/${model}
            mkdir -p $HOME/CMIP6_GCMs_Regridded/${model}
            regridded_models=$HOME/CMIP6_GCMs_Regridded/${model}
            # files=(*)
            # filename=$(echo "${files[0]}")
            # realization=$(echo $filename | cut -d "_" -f 4)
            # echo "Realization: " $realization
            for file in $(ls); do
                echo "Regriding file:" $file
                cdo -P 8 -s remapbil,${samplegrid} ${file} ${file%.*}_regrid.nc 
                echo "Regridded file:" ${file%.*}_regrid.nc
                # cdo -P 8 sellonlatbox,${lon_left},${lon_right},${lat_down},${lat_up} ${file%.*}.nc ${file%.*}_remap.nc
                # rm ${file%.*}_remap.nc
                mv ${file%.*}_regrid.nc ${regridded_models}/${file}
            done
        cd ..
    fi
done