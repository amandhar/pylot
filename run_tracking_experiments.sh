#!/bin/bash

min_matching_ious=(0 0.1 0.25 0.5)
obstacle_track_max_ages=(10)
trackers=("da_siam_rpn" "deep_sort" "sort")
skip_every_nth_dets=(3 4)
trial_nums=(1 2 3)
speeds=(10)

PYLOT_HOME="/home/erdos/workspace/forks/pylot/"
ROOT_SCENARIO_RUNNER="/home/erdos/workspace/forks/scenario_runner/"

for skip in ${skip_every_nth_dets[@]}; do
    for min_matching_iou in ${min_matching_ious[@]}; do
        for max_age in ${obstacle_track_max_ages[@]}; do
            for tracker in ${trackers[@]}; do
                for trial_num in ${trial_nums[@]}; do
                    for target_speed in ${speeds[@]}; do
			file_base=scenario_many-pedestrians-with-turns%tracker_${tracker}%skip_${skip}%min-matching-iou_${min_matching_iou}%max-age_${max_age}%speed_${target_speed}%trial-num_${trial_num}%
		        if [ ! -f "${PYLOT_HOME}/${file_base}.csv" ]; then
                            echo "[x] Running the experiment with tracker $tracker , skip $skip , min_matching_iou $min_matching_iou , max_age $max_age, speed $target_speed trial_num $trial_num"
                            cd $PYLOT_HOME ; python3 scenario_runner.py --flagfile=configs/scenarios/tracker_evaluation.conf --tracker_type=$tracker --skip_every_nth_detection=$skip --obstacle_track_max_age=$max_age --min_matching_iou=$min_matching_iou --target_speed=$target_speed --log_file_name=$file_base.log --csv_log_file_name=$file_base.csv --profile_file_name=$file_base.json --carla_host=carla_v1_aman &
		            cd $ROOT_SCENARIO_RUNNER ; python3 scenario_runner.py --scenario ERDOSManyPedestriansWithTurns --reloadWorld --host=carla_v1_aman --timeout 10
                            echo "[x] Scenario runner finished. Killing Pylot..."
                            pkill --signal 9 -f scenario_runner.py
                        else
                            echo "$file_base exists"
                        fi
		    done
		done
             done
        done
    done
done
