import sys, os

sys.path.append(os.getcwd())  # add current working directory to the path

from epimodel import EpidemiologicalParameters, run_model, preprocess_data
from epimodel.script_utils import *

import argparse
from datetime import datetime

argparser = argparse.ArgumentParser()
argparser.add_argument(
    "--gatherings_aggregation_type",
    dest="gatherings_aggregation_type",
    type=str,
    help="gatherings aggregation. either stricter or weaker",
)
argparser.add_argument(
    "--gatherings_aggregation",
    dest="gatherings_aggregation",
    type=str,
    help="gatherings aggregation. either none, out_in, drop_outdoor",
)

add_argparse_arguments(argparser)
args = argparser.parse_args()

import numpyro

numpyro.set_host_device_count(args.num_chains)

if __name__ == "__main__":
    print(f"Running Sensitivity Analysis {__file__} with config:")
    config = load_model_config(args.model_config)
    pprint_mb_dict(config)

    print("Loading Data")
    data = preprocess_data(get_data_path())
    featurize_arg_dict = config["featurize_kwargs"]
    featurize_arg_dict["gatherings_aggregation_type"] = args.gatherings_aggregation_type
    featurize_arg_dict["gatherings_aggregation"] = args.gatherings_aggregation
    data.featurize(**featurize_arg_dict)
    data.mask_new_variant(new_variant_fraction_fname=get_new_variant_path())
    print("Loading EpiParam")
    ep = EpidemiologicalParameters()
    ep.populate_region_delays(data)

    model_func = get_model_func_from_str(args.model_type)
    ta = get_target_accept_from_model_str(args.model_type)
    td = get_tree_depth_from_model_str(args.model_type)

    base_outpath = generate_base_output_dir(
        args.model_type, args.model_config, args.exp_tag
    )
    ts_str = datetime.now().strftime("%Y-%m-%d;%H:%M:%S")
    summary_output = os.path.join(base_outpath, f"{ts_str}_summary.yaml")
    full_output = os.path.join(base_outpath, f"{ts_str}_full.netcdf")

    model_build_dict = config["model_kwargs"]

    posterior_samples, _, info_dict, _ = run_model(
        model_func,
        data,
        ep,
        num_samples=args.num_samples,
        num_chains=args.num_chains,
        num_warmup=args.num_warmup,
        target_accept=ta,
        max_tree_depth=td,
        model_kwargs=model_build_dict,
        save_results=True,
        output_fname=full_output,
        save_yaml=False,
        chain_method="parallel",
    )

    info_dict["model_config_name"] = args.model_config
    info_dict["model_kwargs"] = config["model_kwargs"]
    info_dict["featurize_kwargs"] = config["featurize_kwargs"]
    info_dict["start_dt"] = ts_str
    info_dict["exp_tag"] = args.exp_tag
    info_dict["exp_config"] = {
        "gatherings_aggregation_type": args.gatherings_aggregation_type,
        "gatherings_aggregation": args.gatherings_aggregation,
    }
    info_dict["cm_names"] = data.CMs
    info_dict["data_path"] = get_data_path()

    # also need to add sensitivity analysis experiment options to the summary dict!
    summary = load_keys_from_samples(
        get_summary_save_keys(), posterior_samples, info_dict
    )
    with open(summary_output, "w") as f:
        yaml.dump(summary, f, sort_keys=True)
