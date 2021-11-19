# Water Allocation Optimization
A tool that uses a linear program to optimize water allocations
when we have data for wells (but not where the water was applied),
demands by parcel (without information on well source), crop
information by parcel, crop associated with well production (sometimes),
and parcel groups and distances that can be assumed to be part of a
connected set.

## Installation
On Windows, requires a conda environment with `cvxpy` and `Django` installed in it.
On Mac/Unix, any python environment with those two libraries is sufficient (so long as
cvxpy can find its dependencies - conda makes that a one-click install)

### Model Setup
Run `python manage.py migrate` to create the database in the same folder
Update the path to your local Box folder in 'WellAllocation/settings.py' - line 18 `BOX_PATH`
Run `python manage.py load_data` to load all of the preprocessed input data into the database

### Running the model

### Interpreting the results

## Input Data
Processed input data is in Box under `VICE Lab/RESEARCH/PROJECTS/Valley_Water/DATA/INPUT DATA`

### Raw Data

### Preprocessing
ArcGIS Models