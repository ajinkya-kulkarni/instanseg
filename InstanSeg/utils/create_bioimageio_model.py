import os
#from PIL import Image
import tifffile

# the imports for bioimage.io model export
import bioimageio.core
import numpy as np
import torch
import monai
from aicsimageio import AICSImage

from InstanSeg.utils.augmentations import Augmentations
from InstanSeg.utils.utils import _choose_device
from InstanSeg.utils.model_loader import load_model


def set_export_paths():
    from pathlib import Path
    if os.environ.get('INSTANSEG_BIOIMAGEIO_PATH'):
        path = Path(os.environ['INSTANSEG_BIOIMAGEIO_PATH'])
    else:
        path = Path(os.path.join(os.path.dirname(__file__),"../bioimageio_models/"))
        os.environ['INSTANSEG_BIOIMAGEIO_PATH'] = str(path)

    if not path.exists():
        path.mkdir(exist_ok=True,parents=True)

    if os.environ.get('INSTANSEG_TORCHSCRIPT_PATH'):
        path = Path(os.environ['INSTANSEG_TORCHSCRIPT_PATH'])
    else:
        path = Path(os.path.join(os.path.dirname(__file__),"../torchscripts/"))
        os.environ['INSTANSEG_TORCHSCRIPT_PATH'] = str(path)

    if not path.exists():
        path.mkdir(exist_ok=True,parents=True)

    if os.environ.get('INSTANSEG_MODEL_PATH'):
        path = Path(os.environ['INSTANSEG_MODEL_PATH'])
    else:
        path = Path(os.path.join(os.path.dirname(__file__),"../models/"))
        os.environ['INSTANSEG_MODEL_PATH'] = str(path)

    if not path.exists():
        path.mkdir(exist_ok=True,parents=True)


dataset_dict = {
    "DSB_2018": ["CC 0","https://bbbc.broadinstitute.org/BBBC038"],
    "CoNSeP": ["Apache 2.0","https://warwick.ac.uk/fac/cross_fac/tia/data/hovernet"],
    "TNBC_2018": ["CC BY 4.0","https://zenodo.org/records/3552674"],
    "MoNuSeg": ["CC BY NC 4.0","https://monuseg.grand-challenge.org/"],
    "LyNSec": ["CC BY 4.0","https://zenodo.org/records/8065174"],
    "LyNSeC": ["CC BY 4.0","https://zenodo.org/records/8065174"],
    "NuInsSeg": ["CC BY 4.0","https://zenodo.org/records/10518968"],
    "IHC_TMA": ["CC BY 4.0","https://zenodo.org/records/7647846"],
    "CPDMI_2023": ["CC BY 4.0","https://www.nature.com/articles/s41597-023-02108-z"],
    "cellpose": ["NC","https://www.cellpose.org/dataset"],
    "TissueNet": ["Modified Apache, Non-Commercial", "https://datasets.deepcell.org/"]
}



from bioimageio.core.build_spec import build_model
from bioimageio.core.resource_tests import test_model

def readme(model_name: str, model_dict: dict = None):
    # create markdown documentation for your model
    # this should describe how the model was trained, (and on which data)
    # and also what to take into consideration when running the model, especially how to validate the model
    # here, we just create a stub documentation

    print(model_dict.keys())
    with open(os.path.join(model_name, model_name + "_README.md"), "w") as f:
        f.write("# This is an InstanSeg model. \n")

        f.write("This model was trained on the following datasets: \n")
        
        if model_dict is not None and "source_dataset" in model_dict.keys():
            for dataset in (model_dict["source_dataset"]).replace("[","").replace("]","").replace("'","").split(", "):
                f.write(f"- {dataset} \n")
                f.write(f"  - License: {dataset_dict[dataset][0]} \n")
                f.write(f"  - Link: {dataset_dict[dataset][1]} \n")

        f.write("The user is responsible for ensuring that the model is used in accordance with the licenses of the source datasets. \n")

          #  f.write(str(model_dict["source_dataset"]))


def modify_yaml_for_qupath_config(yaml_path, pixel_size: float):
    import yaml
    with open(yaml_path, 'r') as file:
        data = yaml.safe_load(file)

    # Modify the YAML data as needed
    data['config']['qupath'] = {
        'axes': [
            {'role': 'x', 'step': pixel_size, 'unit': 'um'},
            {'role': 'y', 'step': pixel_size, 'unit': 'um'}
        ]
    }

    with open(yaml_path, 'w') as file:
        yaml.dump(data, file)

import os, shutil
def make_archive(source, destination):
        base = os.path.basename(destination)
        name = base.split('.')[0]
        format = base.split('.')[1]
        archive_from = os.path.dirname(source)
        archive_to = os.path.basename(source.strip(os.sep))
        shutil.make_archive(name, format, archive_from, archive_to)
        shutil.move('%s.%s'%(name,format), destination)



def export_bioimageio(model: torch.jit._script.RecursiveScriptModule, 
                      model_name: str, 
                      test_img_path: str, 
                      model_dict: dict = None, 
                      output_name = None):
    
    set_export_paths()

    output_path = os.environ['INSTANSEG_BIOIMAGEIO_PATH']


    if output_name is None:
        output_name = model_name
    # create a directory to store bioimage.io model files
    os.makedirs(output_name, exist_ok=True)
    # save the model weights
    model.save(os.path.join(output_name, "instanseg.pt"))

    model_pixel_size = model.pixel_size
    print("Model pixel size: ", model_pixel_size)


    try:
        model,model_dict = load_model(model_name, path = os.environ['INSTANSEG_MODEL_PATH'])
    except:
        raise Exception("Model configuration files could not be loaded")

    model.eval()
    device = _choose_device()
    model.to(device)

    img = AICSImage(test_img_path)
    if "S" in img.dims.order and img.dims.S > img.dims.C:
        input_data = img.get_image_data("SYX")
    else:
        input_data = img.get_image_data("CYX")
        
    if img.physical_pixel_sizes.X is not None:
        pixel_size = img.physical_pixel_sizes.X
        print("Pixel size was found in the metadata, pixel size is set to: ", pixel_size)
    else:
        pixel_size = 0.5
        print("Pixel size was not found in the metadata, please set the pixel size of the input image in microns manually")

    if model_dict["channel_invariant"]:
        dim_in = 1
        step = 1
    else:
        dim_in = model_dict["dim_in"]
        step = 0

    Augmenter=Augmentations()

    input_tensor,_ = Augmenter.to_tensor(input_data,normalize=False) #this converts the input data to a tensor and does percentile normalization (no clipping)

    input_tensor,_ = Augmenter.normalize(input_tensor, percentile=0.)

    import math
    if math.isnan(model_pixel_size):
        model_pixel_size_tmp = pixel_size
    else:
        model_pixel_size_tmp = model_pixel_size
    input_crop,_ = Augmenter.torch_rescale(input_tensor,labels=None,current_pixel_size=pixel_size,requested_pixel_size=model_pixel_size_tmp,crop = True, random_seed=1)

    input_crop = input_crop.unsqueeze(0) # add batch dimension

    if input_crop.shape[1] != dim_in and not model_dict["channel_invariant"]:
        input_crop = torch.zeros((1,dim_in,input_crop.shape[2],input_crop.shape[3]),dtype=torch.float32, device = input_crop.device)

    print("Input tensor shape: ", input_crop.shape)

    # create test data for this model: an input image and an output image
    # this data will be used for model test runs to ensure the model runs correctly and that the expected output can be reproduced
    # NOTE: if you have pre-and-post-processing in your model (see the more advanced models for an example)
    # you will need to save the input BEFORE preprocessing and the output AFTER postprocessing

    np.save(os.path.join(output_name, "test-input.npy"), input_crop.numpy())

    with torch.no_grad():
        output = model(input_crop.to(device))
    np.save(os.path.join(output_name, "test-output.npy"), output.cpu().numpy())

    if model_dict is not None and "source_dataset" in model_dict.keys():
        train_data = str(model_dict["source_dataset"])
    else:
        train_data = "Not specified"


    # create readme
    readme(output_name, model_dict)

    if not os.path.exists(output_path):
        os.makedirs(output_path)


    if os.path.exists(os.path.join(output_path, output_name + ".zip")):
        print("Removing existing model zip")
        os.remove(os.path.join(output_path, output_name + ".zip"))

    # now we can use the build_model function to create the zipped package.
    # it takes the path to the weights and data we have just created, as well as additional information
    # that will be used to add metadata to the rdf.yaml file in the model zip
    # we only use a subset of the available options here, please refer to the advanced examples and to the
    # function signature of build_model in order to get an overview of the full functionality
    _ = build_model(
        # the weight file and the type of the weights
        weight_uri = os.path.join(output_name, "instanseg.pt"),
        weight_type = "torchscript",
        # the test input and output data
        test_inputs = [os.path.join(output_name, "test-input.npy")],
        test_outputs = [os.path.join(output_name, "test-output.npy")],
        # where to save the model zip, how to call the model and a short description of it
        output_path = str(os.path.join(output_path, output_name + ".zip")),
        name = output_name,
        description = "InstanSeg Fluorescence",
        # additional metadata about authors, licenses, citation etc.
        authors = [{"name": "Thibaut Goldsborough et al. TODO"}],
        license = "Apache 2.0",
        documentation = os.path.join(output_name, output_name + "_README.md"),
        tags = ["cell-segmentation"],  # the tags are used to make models more findable on the website
        cite = [{"text": "Thibaut Goldsborough et al.", "doi": "TODO"}],
        # description of the tensors
        # these are passed as list because we support multiple inputs / outputs per model
        input_names = ["raw"],
        input_axes = ["bcyx"],
        input_min_shape = [[1, dim_in, 128, 128]],
        input_step = [[0, step, 32, 32]],
        output_names = ["instance"],
        output_axes=["bcyx"],
        output_reference = ["raw"],
        output_scale = [[1.0, 1.0, 1.0, 1.0]],
        output_offset = [[0.0, 0.0, 0.0, 0.0]],
        preprocessing = None,
        pytorch_version = str(torch.__version__),
        add_deepimagej_config = True,
      #  pixel_sizes = [{"x":float(model_pixel_size),"y":float(model_pixel_size)}],
    )

    # finally, we test that the expected outptus are reproduced when running the model.
    # the 'test_model' function runs this test.
    # it will output a list of dictionaries. each dict gives the status of a different test that is being run
    # if all of them contain "status": "passed" then all tests were successful
    my_model = bioimageio.core.load_resource_description(os.path.join(output_path, output_name + ".zip")) 
    test_model(my_model)

    #Cleanup 

    os.remove("cover.png")
    os.remove("test-output.npy")
    os.remove("test-input.npy")
    os.remove("instanseg.pt")
    os.remove(output_name + "_README.md")
    os.remove("sample_output_0.tif")
    os.remove("sample_input_0.tif")

    #unzip the folder

    
    import zipfile
    import shutil

    input = os.path.join(output_path, output_name + ".zip")
    destination = os.path.join(output_path, output_name)
    with zipfile.ZipFile(input, 'r') as zip_ref:
        zip_ref.extractall(destination)
    
    yaml_path = os.path.join(destination, 'rdf.yaml')
    modify_yaml_for_qupath_config(yaml_path, pixel_size=model_pixel_size)

    
    make_archive(destination, input)


    

    

    shutil.rmtree(output_name)