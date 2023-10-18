import datetime
import json
import logging
import re
from typing import Dict, List, Any
import yaml
from fhir.resources.codesystem import *
from fhir.resources.coding import Coding
from fhir.resources.fhirtypes import CodingType
from fhir.resources.identifier import Identifier
from fhir.resources.narrative import Narrative
from fhir.resources.valueset import (ValueSet,
                                     ValueSetCompose,
                                     ValueSetComposeInclude,
                                     ValueSetComposeIncludeConcept,
                                     ValueSetComposeIncludeConceptDesignation)
from edqm_api import EdqmApi


def safe_get(dictionary: Dict[str, Any], key: str, default: Any = None) -> Any:
    if key in dictionary:
        value = dictionary[key]
        if isinstance(value, str):
            value = value.strip()
            return value if value != "" and value is not None else default
        else:
            if value is None:
                return default
            else:
                return value
    return default


class App:
    edqm_api: EdqmApi
    metadata_file: str
    fhir_metadata: Dict
    code_system_settings: Dict
    value_set_settings: Dict
    generated_on: str
    designation_languages: List[str]
    vs_designations: bool
    cs_link_categories: List[str] = []
    class_code_system_url: str | None
    concept_classes: List[CodeSystemConcept] | None
    version: str

    def __init__(self, username, password, metadata_file, designation_languages, vs_designations):
        self.edqm_api = EdqmApi(username, password)
        self.metadata_file = metadata_file
        self.designation_languages = designation_languages
        self.vs_designations = vs_designations
        self.__load_config_yaml()
        self.__verify_classes()
        self.__verify_designation_languages()
        self.generated_on = datetime.date.today().strftime("%Y-%m-%d")
        self.version = self.generated_on.replace("-", "")
        self.class_code_system_url = None
        self.concept_classes = None

    @staticmethod
    def __replace_placeholders(original_value: str, **kwargs):
        mutated_value = original_value
        for k, v in kwargs.items():
            placeholder = "<$" + k + "$>"
            mutated_value = mutated_value.replace(placeholder, v)
        return mutated_value

    @staticmethod
    def __generate_name_from_title(param: str) -> str:
        return param.replace(" ", "_").replace("_-_", "-")

    @staticmethod
    def __generate_id_from_title(param: str) -> str:
        regexes = {
            "\\s": "-",  # all whitespace
            "-+": "-",  # multiple dashed after replacement
            "[()]": "",  # opening and closing brackets should be removed
            "[^A-Za-z0-9\\-.]": "_"  # inverted character class to replace all non-matching chars
        }
        replaced = param
        for (pattern, replace) in regexes.items():
            replaced = re.sub(pattern=pattern, repl=replace, string=replaced)
        return replaced.lower()

    @staticmethod
    def __reformat_datetime(input_str: str) -> str:
        return input_str.replace(" ", "T") + "Z"

    @staticmethod
    def __get_concept_property_concept_class(concept: CodeSystemConcept):
        prop: List[CodeSystemConceptProperty] = list(filter(lambda c: c.code == "concept_class", concept.property))
        if len(prop) != 1:
            raise RuntimeError(f"No property for the concept class was found in concept {concept.code}")
        value_coding: CodingType = prop[0].valueCoding
        # noinspection PyUnresolvedReferences
        return value_coding.code

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

    def __cs_build_concept_properties(self,
                                      concept_class: str,
                                      domain: str,
                                      creation_date: str,
                                      modification_date: str,
                                      links: Dict[str, List[Dict[str, str]]],
                                      status: str) -> List[CodeSystemConceptProperty]:

        class_coding = Coding(**{
            "system": self.class_code_system_url,
            "code": concept_class,
            "display": [x.display for x in self.concept_classes if x.code == concept_class][0]
        })

        properties = [
            CodeSystemConceptProperty(**{"code": "concept_class", "valueCoding": class_coding}),
            CodeSystemConceptProperty(**{"code": "domain", "valueString": domain}),
            CodeSystemConceptProperty(**{
                "code": "creation_date",
                "valueDateTime": self.__reformat_datetime(creation_date)
            }),
            CodeSystemConceptProperty(**{
                "code": "modification_date",
                "valueDateTime": self.__reformat_datetime(modification_date)
            }),
            CodeSystemConceptProperty(**{"code": "status", "valueCode": status})
        ]
        if status.lower() != "current":
            properties.append(CodeSystemConceptProperty(**{
                "code": "inactive",
                "valueBoolean": True
            }))

        for link_category in links.keys():
            for link in links[link_category]:
                properties.append(CodeSystemConceptProperty(**{
                    "code": "child",
                    "valueCode": link["code"]
                }))

        return properties

    @staticmethod
    def __cs_build_designations(translations) -> List[CodeSystemConceptDesignation]:
        designations = []
        for lang, translation in translations.items():
            # explicit for loop rather than some kind of generator expression,
            # since we need to catch some cases where no translation is set in the EDQM
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
                # this logs exceptions, but doesn't abort execution,
                # since this is "only" dealing with designations
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
            definition = safe_get(concept, "definition")
            translations = {translation["language"]: translation["term"] for translation in concept["translations"] if
                            translation["language"] in self.designation_languages}
            links = safe_get(concept, "links", {})
            status = concept["status"]
            fhir_concept = CodeSystemConcept(**{
                "code": code,
                "display": display,
                "definition": definition,
                "designation": self.__cs_build_designations(translations),
                "property": self.__cs_build_concept_properties(concept_class, domain, creation_date,
                                                               modification_date,
                                                               links,
                                                               status)
            })
            fhir_concepts.append(fhir_concept)
        return fhir_concepts

    def __cs_generate_properties(self):
        properties = []
        prop_definitions = self.code_system_settings["all_codes"]["properties"]
        for prop_code, prop_definition in prop_definitions.items():
            description = safe_get(prop_definition, "description")
            uri = safe_get(prop_definition, "uri")
            prop_type = prop_definition["type"]
            properties.append(CodeSystemProperty(**{
                "code": prop_code,
                "type": prop_type,
                "uri": uri,
                "description": description
            }))
        return properties

    def __generate_div(self, resource: CodeSystem | ValueSet) -> Narrative:
        description = resource.description
        title = resource.title
        canonical = resource.url
        div_template: str = self.fhir_metadata["div_template"]
        div = App.__replace_placeholders(div_template, title=title, canonical=canonical, description=description)
        return Narrative(**{
            "status": "generated",
            "div": div
        })

    def __generate_canonical(self, **kwargs) -> str:
        generated_url = self.fhir_metadata["url_template"]
        for k, v in kwargs.items():
            # `**{k: v}` destructures the dictionary into kwargs, since writing `k=v` doesn't mean what we want
            generated_url = App.__replace_placeholders(generated_url, **{k: v})
        return generated_url

    def __load_config_yaml(self):
        with open(self.metadata_file, "r") as yaml_file:
            y = yaml.safe_load(yaml_file)
        self.fhir_metadata = y["fhir_metadata"]
        self.code_system_settings = y["code_systems"]
        self.value_set_settings = y["value_sets"]

    def __verify_classes(self):
        classes = self.edqm_api.execute_request("/classes")
        api_classes = [c["code"] for c in classes["content"]]
        definitions = self.value_set_settings["definitions"]

        configured_codes = [vs["class"] for _, vs in definitions.items()]
        for code in configured_codes:
            if code not in api_classes:
                raise RuntimeError(f"The class {code} was not configured in the {self.metadata_file} file. Aborting.")
        logging.info("Successfully verified all classes in the API are configured in the %s file", self.metadata_file)

    def __vs_map_designations_from_cs(self, designation: List[CodeSystemConceptDesignation] | None) -> (
            List[ValueSetComposeIncludeConceptDesignation] | None):
        if designation is None or not self.vs_designations:
            return None

        desi = [ValueSetComposeIncludeConceptDesignation(**{
            "language": cd.language,
            "use": cd.use,
            "value": cd.value
        }) for cd in designation]
        return desi

    def generate_class_code_system(self) -> CodeSystem:
        output_cs = CodeSystem(**{
            "status": "active",
            "content": "complete",
            "experimental": False,
            "caseSensitive": False,
            "meta": {
                "profile": self.code_system_settings["profiles"]
            }
        })
        class_code_system_settings = self.code_system_settings["concept_classes"]
        output_cs.name = self.__generate_name_from_title(class_code_system_settings["title"])
        output_cs.id = self.__generate_id_from_title(class_code_system_settings["title"])
        output_cs.title = class_code_system_settings["title"]
        output_cs.url = self.__generate_canonical(resource_type="CodeSystem", id_slug=output_cs.id)
        output_cs.valueSet = self.__generate_canonical(resource_type="ValueSet", id_slug=output_cs.id)
        output_cs.date = self.generated_on
        output_cs.version = self.version
        output_cs.copyright = self.fhir_metadata["copyright"]
        output_cs.publisher = self.fhir_metadata["publisher"]
        output_cs.description = App.__replace_placeholders(class_code_system_settings["description"],
                                                           date=self.generated_on)
        output_cs.text = self.__generate_div(output_cs)
        self.class_code_system_url = output_cs.url
        concepts = []
        api_classes = self.edqm_api.execute_request("/classes")
        for api_class in api_classes["content"]:
            concepts.append(CodeSystemConcept(**{
                "code": api_class["code"],
                "display": api_class["name"]
            }))
        output_cs.concept = concepts
        self.concept_classes = concepts
        output_cs.count = len(output_cs.concept)

        return output_cs

    def create_code_system(self) -> CodeSystem:
        logging.info("Requesting full set of concepts, this generally takes a while")
        # all_terms = self.edqm_api.execute_request("/full_data_by_class/1/1/1") # concept1=1, etc. gets all concepts
        # with open("output.json", "w") as jf:
        #    json.dump(all_terms, jf, indent=2)
        with open("output.json", "r") as jf:
            all_terms = json.load(jf)
        logging.info("Retrieved full list of concepts from the API")

        cs_settings = self.code_system_settings["all_codes"]

        output_cs = CodeSystem(**{
            "status": "active",
            "content": "complete",
            "experimental": False,
            "caseSensitive": False,
            "meta": {
                "profile": self.code_system_settings["profiles"]
            }
        })
        output_cs.name = self.__generate_name_from_title(cs_settings["title"])
        output_cs.id = self.__generate_id_from_title(cs_settings["title"])
        output_cs.title = cs_settings["title"]
        output_cs.url = self.__generate_canonical(resource_type="CodeSystem", id_slug=output_cs.id)
        output_cs.valueSet = self.__generate_canonical(resource_type="ValueSet", id_slug=output_cs.id)
        output_cs.date = self.generated_on
        output_cs.version = self.version
        output_cs.copyright = self.fhir_metadata["copyright"]
        output_cs.publisher = self.fhir_metadata["publisher"]
        output_cs.description = App.__replace_placeholders(cs_settings["description"], date=self.generated_on)
        output_cs.identifier = [Identifier(**{
            "system": self.fhir_metadata["identifier_systems"]["oid"]["system"],
            "value": f"{self.fhir_metadata['identifier_systems']['oid']['prefix']}{cs_settings['oid']}"
        })]
        output_cs.text = self.__generate_div(output_cs)
        output_cs.property = self.__cs_generate_properties()
        output_cs.concept = self.__cs_generate_concepts(all_terms)
        output_cs.count = len(output_cs.concept)
        return output_cs

    def create_value_sets(self, code_system: CodeSystem) -> List[ValueSet]:
        vs = []
        for (valueset_name, valueset_settings) in self.value_set_settings["definitions"].items():
            output_vs = self.__generate_value_set(valueset_name, valueset_settings, code_system)
            vs.append(output_vs)
        return vs

    def __generate_value_set(self, valueset_name: str, valueset_params: Dict, code_system: CodeSystem):
        output_vs = ValueSet(**{
            "status": "active",
            "version": self.version,
            "date": self.generated_on,
            "copyright": self.fhir_metadata["copyright"],
            "publisher": self.fhir_metadata["publisher"]
        })
        output_vs.title = App.__replace_placeholders(self.value_set_settings['title_template'], vs_name=valueset_name)
        output_vs.id = self.__generate_id_from_title(output_vs.title)
        output_vs.name = self.__generate_name_from_title(output_vs.title)
        output_vs.url = self.__generate_canonical(resource_type="ValueSet", id_slug=output_vs.id)
        output_vs.description = App.__replace_placeholders(self.value_set_settings["description"],
                                                           title=valueset_name,
                                                           class_code=valueset_params["class"],
                                                           date=self.generated_on)
        output_vs.identifier = [Identifier(**{
            "system": self.fhir_metadata["identifier_systems"]["oid"]["system"],
            "value": f"{self.fhir_metadata['identifier_systems']['oid']['prefix']}{valueset_params['oid']}"
        })]
        output_vs.text = self.__generate_div(output_vs)

        included_concepts = filter(lambda c: App.__get_concept_property_concept_class(c) == valueset_params["class"],
                                   code_system.concept)
        vs_concepts = list(map(lambda c: ValueSetComposeIncludeConcept(**{
            "code": c.code,
            "display": c.display,
            "designation": self.__vs_map_designations_from_cs(c.designation)
        }), included_concepts))

        include = ValueSetComposeInclude(**{
            "system": code_system.url,
            "version": code_system.version,
            "concept": vs_concepts
        })
        output_vs.compose = ValueSetCompose(**{
            "inactive": False,
            "include": [include]
        })

        return output_vs
