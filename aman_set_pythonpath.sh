export PYTHONPATH=
export PYLOT_HOME=`pwd`
cd dependencies/CARLA_0.9.8/
export CARLA_HOME=`pwd`
cd ../..
source scripts/set_pythonpath.sh
export PYTHONPATH=$PYTHONPATH:/home/erdos/workspace/forks/pylot/dependencies/automl/efficientdet
echo $PYTHONPATH
