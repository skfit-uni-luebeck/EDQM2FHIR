import logging
import os
import pathlib
from typing import Tuple
import click
from fhir.resources.codesystem import CodeSystem
from fhir.resources.valueset import ValueSet

from edqm2fhir_app import App


def __generate_output_filename(output_dir: str, resource_type: str, id: str):
    filename = f"{resource_type}_{id}.fhir.json"
    return os.path.join(output_dir, filename)


def __write_file(resource: CodeSystem | ValueSet, output_dir: str):
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)
        logging.info("Created output dir %s", os.path.abspath(output_dir))
    filename = __generate_output_filename(output_dir, resource.resource_type, resource.id)
    logging.info(f"Writing {resource.resource_type} file to {os.path.abspath(filename)}")
    with open(filename, "w") as of:
        of.write(resource.json(indent=2))


@click.command(epilog="You can also provide arguments via environment variables, e.g. EDQM2FHIR_API_KEY and so on.")
@click.option("--username",
              "-u",
              required=True,
              help="Your username (e-mail) for the EDQM API")
@click.option("--api-key",
              "-k",
              required=True,
              help="Your personal API key for the EDQM API.")
@click.option("--metadata-file",
              required=True,
              default="./metadata.yml")
@click.option("--designation", "-d",
              multiple=True,
              default=["all"]
              )
@click.option("--output", "-o", "output_dir",
              required=True,
              default="output")
def convert(
        username: str,
        api_key: str,
        metadata_file: str,
        designation: Tuple[str],
        output_dir: str
):
    app = App(username, api_key, metadata_file, [d for d in designation])
    ccs = app.generate_class_code_system()
    __write_file(ccs, output_dir)
    cs = app.create_code_system()
    __write_file(cs, output_dir)

    vss = app.create_value_sets()
    for vs in vss:
        __write_file(vs, output_dir)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    convert(auto_envvar_prefix="EDQM2FHIR")
