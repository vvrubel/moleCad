from typing import Any, Dict, List

from loguru import logger
from mongordkit.Search import substructure
from pydantic import NonNegativeInt, PositiveInt
from pymongo.cursor import Cursor
from rdkit import Chem

from .errors import NoDatabaseRecordError
from .settings import settings
from .utils import timer

db = settings.get_db()


def paging_pipeline(mol_lst: List[str], skip: int, limit: int) -> List[Dict[str, Any]]:
    """
    Функция принимает на вход список отфильтрованных молекул и параметры пагинации,
    подставляет эти значения в стадии пайплана и возвращает их список из функции.
    :param mol_lst: Список молекул из функции ``run_search``.
    :param skip: Число записей, которые нужно пропустить.
    :param limit: Число записей, которые нужно показать.
    :return: Список стадий.
    """
    match_ = {"$match": {"index": {"$in": mol_lst}}}
    project_ = {"$project": {"_id": 0, "index": 0}}
    skip_ = {"$skip": skip}
    limit_ = {"$limit": limit}
    return [match_, project_, skip_, limit_]


def summary_pipeline(mol_lst: List[str]) -> List[Dict[str, Any]]:
    """
    Функция принимает на вход список отфильтрованных молекул и строит пайплайн, в котором
    оставляет документы со smiles из входящего списка, затем группирует все
    документы и рассчитывает статистические параметры для числовых полей.
    :param mol_lst: Список молекул из функции ``run_search``.
    :return: Список стадий.
    """
    match_ = {"$match": {"index": {"$in": mol_lst}}}
    group_ = {
        "$group": {
            "_id": 0,
            "n_compounds": {"$sum": 1},
            "AvgMolW": {"$avg": "$MolecularWeight"},
            "StdMolW": {"$stdDevPop": "$MolecularWeight"},
            "AvgLogP": {"$avg": "$XLogP"},
            "StdLogP": {"$stdDevPop": "$XLogP"},
            "AvgDonor": {"$avg": "$HBondDonorCount"},
            "StdDonor": {"$stdDevPop": "$HBondDonorCount"},
            "AvgAcceptor": {"$avg": "$HBondAcceptorCount"},
            "StdAcceptor": {"$stdDevPop": "$HBondAcceptorCount"},
            "AvgRotatable": {"$avg": "$RotatableBondCount"},
            "StdRotatable": {"$stdDevPop": "$RotatableBondCount"},
            "AvgAtomStereo": {"$avg": "$AtomStereoCount"},
            "StdAtomStereo": {"$stdDevPop": "$AtomStereoCount"},
            "AvgBondStereo": {"$avg": "$BondStereoCount"},
            "StdBondStereo": {"$stdDevPop": "$BondStereoCount"},
            "AvgVol3D": {"$avg": "$Volume3D"},
            "StdVol3D": {"$stdDevPop": "$Volume3D"},
        }
    }
    project_ = {
        "$project": {
            "_id": 0,
            "MolecularWeight": {
                "Average": {"$round": ["$AvgMolW", 2]},
                "StandardDeviation": {"$round": ["$StdMolW", 2]},
            },
            "XLogP": {
                "Average": {"$round": ["$AvgLogP", 2]},
                "StandardDeviation": {"$round": ["$StdLogP", 2]},
            },
            "HBondDonorCount": {
                "Average": {"$round": ["$AvgDonor", 2]},
                "StandardDeviation": {"$round": ["$StdDonor", 2]},
            },
            "HBondAcceptorCount": {
                "Average": {"$round": ["$AvgAcceptor", 2]},
                "StandardDeviation": {"$round": ["$StdAcceptor", 2]},
            },
            "RotatableBondCount": {
                "Average": {"$round": ["$AvgRotatable", 2]},
                "StandardDeviation": {"$round": ["$StdRotatable", 2]},
            },
            "AtomStereoCount": {
                "Average": {"$round": ["$AvgAtomStereo", 2]},
                "StandardDeviation": {"$round": ["$StdAtomStereo", 2]},
            },
            "BondStereoCount": {
                "Average": {"$round": ["$AvgBondStereo", 2]},
                "StandardDeviation": {"$round": ["$StdBondStereo", 2]},
            },
            "Volume3D": {
                "Average": {"$round": ["$AvgVol3D", 2]},
                "StandardDeviation": {"$round": ["$StdVol3D", 2]},
            },
        }
    }
    return [match_, group_, project_]


def search_substructures(smiles: str) -> List[str]:
    """
    Функция генерирует объект молекулы для работы rdkit, после этот объект используется для
    подструктурного поиска по коллекции "molecules".
    :param smiles: Строковое представление структуры молекулы.
    :return: Список молекул, удовлетворяют результатам поиска по заданной подструктуре.
    """
    q_mol: Chem.Mol = Chem.MolFromSmiles(smiles)
    search_results: List[str] = substructure.SubSearch(q_mol, db[settings.molecules])

    if len(search_results) == 0:
        raise NoDatabaseRecordError
    else:
        logger.success(f"Found {len(search_results)} compounds for requested pattern.")
        return search_results


@timer
def run_page_search(smiles: str, skip: NonNegativeInt, limit: PositiveInt) -> List[Cursor]:
    logger.info(f"Searching molecules for the substructure: {smiles}")
    mol_lst = search_substructures(smiles)
    logger.info(f"Applying the pagination parameters: skip – {skip}, limit – {limit}")
    pipeline = paging_pipeline(mol_lst, skip, limit)
    cursor = db[settings.properties].aggregate(pipeline)
    return list(cursor)


@timer
def run_summary_search(smiles: str) -> List[Cursor]:
    logger.info(f"Searching molecules for substructure: {smiles}")
    mol_lst = search_substructures(smiles)
    logger.info("Calculating the statistics for searched molecules.")
    pipeline = summary_pipeline(mol_lst)
    cursor = db[settings.properties].aggregate(pipeline)
    return list(cursor)