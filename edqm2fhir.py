import datetime
import json
import logging
import os
from typing import Dict, List, Tuple
import click
import yaml
from fhir.resources.codesystem import *
from edqm_api import EdqmApi
import re


def generate_output_filename(output_dir, resource_type, id):
    filename = f"{resource_type}_{id}.fhir.json"
    return os.path.join(output_dir, filename)


class App:
    edqm_api: EdqmApi
    metadata_file: str
    fhir_metadata: Dict
    code_system_settings: Dict
    value_set_settings: Dict
    generated_on: str
    designation_languages: List[str]
    cs_link_categories: List[str] = []

    def __init__(self, username, password, metadata_file, designation):
        self.edqm_api = EdqmApi(username, password)
        self.metadata_file = metadata_file
        self.designation_languages = designation
        self.__load_config_yaml()
        self.__verify_classes()
        self.__verify_designation_languages()
        self.generated_on = datetime.date.today().strftime("%Y-%m-%d")

    def __load_config_yaml(self):
        with open(self.metadata_file, "r") as yaml_file:
            y = yaml.safe_load(yaml_file)
        self.fhir_metadata = y["fhir_metadata"]
        self.code_system_settings = y["code_system"]
        self.value_set_settings = y["value_sets"]

    def __verify_classes(self):
        classes = self.edqm_api.execute_request("/classes")
        api_classes = [c["code"] for c in classes["content"]]
        definitions = self.value_set_settings["definitions"]

        configured_codes = [vs["class"] for _, vs in definitions.items()]
        for code in configured_codes:
            if code not in api_classes:
                raise RuntimeError(f"The class {code} was not configured in the {self.metadata_file} file. Aborting.")
        logging.info("Verified all classes in the API are configured in the %s file", self.metadata_file)

    def create_code_system(self) -> CodeSystem:
        logging.info("Requesting full set of concepts, this generally takes a while")
        # all_terms = self.edqm_api.execute_request("/full_data_by_class/1/1/1") # concept1=1, etc. gets all concepts
        # with open("output.json", "w") as jf:
        #    json.dump(all_terms, jf, indent=2)
        with open("output.json", "r") as jf:
            all_terms = json.load(jf)
        logging.info("Retrieved full list of concepts from the API")
        fhir_concepts = self.__cs_generate_concepts(all_terms)
        output_cs = CodeSystem(**{
            "status": "active",
            "content": "complete"
        })
        output_cs.name = self.__generate_name_from_title(self.code_system_settings["title"])
        output_cs.id = self.__generate_id_from_title(self.code_system_settings["title"])
        output_cs.title = self.code_system_settings["title"]
        output_cs.url = self.__generate_canonical(resource_type="CodeSystem", id_slug=output_cs.id)
        output_cs.date = self.generated_on
        output_cs.version = self.generated_on.replace("-", "")
        output_cs.copyright = self.fhir_metadata["copyright"]
        output_cs.description = self.code_system_settings["description"].replace("<date>", self.generated_on)
        output_cs.property = self.__cs_generate_properties()
        output_cs.concept = fhir_concepts
        return output_cs

    def create_value_sets(self):
        pass

    def __verify_designation_languages(self):
        languages = self.edqm_api.execute_request("/languages")["content"]
        if "all" in self.designation_languages:
            self.designation_languages = sorted([lang["code"] for lang in languages])
            logging.info("Generating designation in all languages available.")
        else:
            matching_languages = {lang["code"]: lang["name"] for lang in languages if
                                  lang["code"] in self.designation_languages}
            missing_codes = [d for d in self.designation_languages if d not in matching_languages.keys()]
            if any(missing_codes):
                raise RuntimeError(f"Language code/-s unsupported by EDQM: {','.join(missing_codes)}")
            logging.info(f"Generating designations in: {', '.join([c for c in matching_languages.values()])}")

    @staticmethod
    def __reformat_datetime(input_str: str) -> str:
        return input_str.replace(" ", "T") + "Z"

    def __cs_build_properties(self, concept_class: str, domain: str, creation_date: str, modification_date: str,
                              links: Dict[str, List[Dict[str, str]]], status) -> List[CodeSystemConceptProperty]:

        properties = [
            CodeSystemConceptProperty(**{"code": "concept_class", "valueString": concept_class}),
            CodeSystemConceptProperty(**{"code": "domain", "valueString": domain}),
            CodeSystemConceptProperty(**{
                "code": "creation_date",
                "valueDateTime": self.__reformat_datetime(creation_date)
            }),
            CodeSystemConceptProperty(**{
                "code": "modification_date",
                "valueDateTime": self.__reformat_datetime(modification_date)
            }),
            CodeSystemConceptProperty(**{"code": "status", "valueString": status})
        ]

        for link_category in links.keys():
            link_code = f"link_{link_category.lower()}"
            if link_code not in self.cs_link_categories:
                self.cs_link_categories.append(link_code)
            for link in links[link_category]:
                properties.append(CodeSystemConceptProperty(**{
                    "code": link_code,
                    "valueCode": link["code"]
                }))

        return properties

    @staticmethod
    def __cs_build_designations(translations) -> List[CodeSystemConceptDesignation]:
        designations = []
        for lang, translation in translations.items():
            # explicit for loop, since we need to catch some cases where no translation is set in the EDQM
            if not translation:
                continue
            try:
                designations.append(
                    CodeSystemConceptDesignation(**{
                        "language": lang,
                        "value": translation
                    })
                )
            except ValidationError as e:
                logging.exception(e)
                # this logs exceptions, but doesn't abort execution, since this is "only" dealing with designations
        return designations

    def __cs_generate_concepts(self, all_terms: Dict):
        fhir_concepts = []
        for concept in all_terms["content"]:
            code = concept["code"]
            concept_class = concept["class"]
            domain = concept["domain"]
            creation_date = concept["creation_date"]
            modification_date = concept["modification_date"]
            display = concept["english"]
            definition = concept["definition"] if concept["definition"] else None
            translations = {trans["language"]: trans["term"] for trans in concept["translations"] if
                            trans["language"] in self.designation_languages}
            links = concept.get("links", {})
            status = concept["status"]
            try:
                fhir_concept = CodeSystemConcept(**{
                    "code": code,
                    "display": display,
                    "definition": definition,
                    "designation": self.__cs_build_designations(translations),
                    "property": self.__cs_build_properties(concept_class, domain, creation_date, modification_date,
                                                           links,
                                                           status)
                })
                fhir_concepts.append(fhir_concept)
            except ValidationError as e:
                logging.exception(e)
        return fhir_concepts

    @staticmethod
    def __generate_name_from_title(param: str) -> str:
        return param.replace(" ", "_")

    @staticmethod
    def __generate_id_from_title(param: str) -> str:
        return param.replace(" ", "-").lower()

    def __generate_canonical(self, **kwargs) -> str:
        generated_url = self.fhir_metadata["url_template"]
        for k, v in kwargs.items():
            generated_url = generated_url.replace(f"<{k}>", v)
        return generated_url

    def __cs_generate_properties(self):
        # TODO implement:
        # domain, class, creation_date, modification_date, links (with sub-codes)
        return []


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
@click.option("--output", "-o",
              required=True,
              default="output")
def convert(
        username: str,
        api_key: str,
        metadata_file: str,
        designation: Tuple[str],
        output: str
):
    app = App(username, api_key, metadata_file, [d for d in designation])
    if not os.path.isdir(output):
        os.mkdir(output)
        logging.info("Created output dir %s", os.path.abspath(output))
    cs = app.create_code_system()
    with open(generate_output_filename(os.path.abspath(output), "CodeSystem", cs.id), "w") as of:
        of.write(cs.json(indent=2))

    app.create_value_sets()


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.INFO)
    convert(auto_envvar_prefix="EDQM2FHIR")
