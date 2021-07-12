import time
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    TypeVar,
    Union,
)

import requests
from loguru import logger

from molecad.data.utils import (
    chunked,
    concat,
    generate_ids,
)
from molecad.errors import (
    BadDomainError,
    BadNamespaceError,
    BadOperationError,
)
from molecad.types_ import (
    Domain,
    NamespCmpd,
    OperationComplex,
    Out,
    PropertyTags,
)
from molecad.validator import (
    is_complex_operation,
    is_compound,
    is_namespace_search,
    is_simple_namespace,
    is_simple_operation,
)

IdT = TypeVar("IdT", int, str)
T = TypeVar("T")
BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def url_builder(
    ids: Union[IdT, Iterable[IdT]],
    *,
    domain: str,
    namespace_prefix: str,
    namespace_suffix: Optional[str] = None,
    operation: str,
    tags: Optional[Sequence[str]] = None,
    output: str,
) -> str:
    """
    Команда генерирует строку URL-адреса, необходимую для выполнения запроса в службу PubChem.
    :param ids: число, строка или последовательность из значений одинакового типа,
    которые интерпретируются как идентификаторы соединений; последовательность идентификаторов может
    быть получена в результате выполнения функции ``generate_ids`` или ``chunked``.
    :param domain: принимает значение из класса ``Domain``, по умолчанию установлено значение
    ``Domain.COMPOUND``.
    .. note:: В текущей версии сервиса доступен поиск только по базе данных ``Compound``.
    :param namespace_prefix: передается в функцию ``joined_namespace`` в качестве ``prefix``,
    который может принимать значения из классов ``NamespCmpd`` и ``PrefixSearch`` в данной
    версии сервиса. Значение по умолчанию - ``NamespCmpd.CID``.
    .. note:: В текущей версии сервиса доступен поиск только по пространству имен ``CID``.
    :param namespace_suffix: передается в функцию ``joined_namespace`` в качестве ``suffix`` и
    принимает значения из класса ``SuffixSearch``; по умолчанию - None
    .. note:: В текущей версии сервиса значение параметра - None.
    :param operation: принимает значения в зависимости от определенного ранее параметра
    ``domain``. Аргумент может принимать значения из классов ``Operation``, ``OperationComplex``.
    Если значение не определено, то по умолчанию извлекается вся запись, т.е. значение равно
    ``Operation.RECORD``.
    .. note:: В текущей версии сервиса доступна операции, поиск по которым выполняется в базе
    данных ``Compound``, а формат их выходных данных должен представлять собой JSON.
    :param tags: определяется только в случае если ``operation`` == ``Operation.PROPERTY``,
    иначе не указывается; строка содержит перечень из запрашиваемых тегов, доступных для данной
    операции, которые передаются в функцию ``join_w_comma`` и далее в ``operation_specification``.
    :param output: принимает значение из класса ``Out`` и напрямую передается в функцию
    ``build_url``; по умолчанию - ``Out.JSON``.
    .. note:: В текущей версии сервиса получение ответа от сервера возможно только в формате JSON.
    :return: URL-адрес, который используется для запроса в базу данных Pubchem.
    """

    if not is_compound(domain):
        raise BadDomainError

    if is_simple_namespace(namespace_prefix, namespace_suffix):
        joined_namespaces = namespace_prefix
    elif is_namespace_search(namespace_prefix, namespace_suffix):
        joined_namespaces = concat(namespace_prefix, namespace_suffix)
    else:
        raise BadNamespaceError

    joined_identifiers = concat(*ids, sep=",")
    input_spec = concat(domain, joined_namespaces, joined_identifiers)

    if is_complex_operation(operation, tags):
        joined_tags = concat(*tags, sep=",")
        operation_spec = concat(operation, joined_tags)
    elif is_simple_operation(operation, tags):
        operation_spec = operation
    else:
        raise BadOperationError

    url = concat(BASE_URL, input_spec, operation_spec, output)
    return url


def request_property_data_json(url: str, **operation_options: str) -> List[Dict[str, Any]]:
    """
    Функция добавляет параметры к URL, если они переданы в переменную ``operation_options`` и
    отправляет синхронный GET-запрос к серверам PUG REST баз данных Pubchem.
    Если бы вы создавали URL-адрес вручную, пары значений из словаря ``operation_options``
    записывались бы в конец URL-адреса после знака ``?`` в виде ``key=value``, а при наличии
    более одной пары последние объединялись знаком ``&``.
    :param url: возвращается из функции ``url_builder`` и является обязательным для всех
    запросов.
    :param operation_options: может быть None или словарем из строк в случае определенных
    значений параметра ``operation`` в функции ``url_builder``.
    :return: ответ от сервера в формате JSON .
    """
    response = requests.get(url, params=operation_options).json()
    return response["PropertyTable"]["Properties"]


def delay_iterations(
    iterable: Iterable[T], waiting_time: float = 60.0, maxsize: int = 400
) -> Iterator[T]:
    """
    Ограничения на запросы, совершаемые в службу PubChem PUG REST:
    * Не больше 5 запросов в секунду.
    * Не больше 400 запросов в минуту.
    * Суммарное время обработки запросов, отправленных в течение минуты, не должно превышать 300
    секунд.
    :param iterable: последовательности идентификаторов, полученных из функции ``chunked``.
    :param waiting_time: 60 секунд.
    :param maxsize: 400 запросов.
    :return: генерирует последовательность в соответствии с ограничениями Pubchem.
    """
    window = []
    for i in iterable:
        yield i
        t = time.monotonic()
        window.append(t)
        while t - waiting_time > window[0]:
            window.pop(0)
        if len(window) > maxsize:
            t0 = window[0]
            delay = t - t0
            time.sleep(delay)


def execute_requests(start: int, stop: int, maxsize: int = 100) -> Iterator[Dict[str, Any]]:
    """
    Извлекает и сохраняет информацию из базы данных Pubchem – 'Compound'; генерирует списки
    идентификаторов равной длины, исходя из параметров в сигнатуре функции, и передает их вместе с
    остальными параметрами, определенными внутри функции, в ``url_builder``, после чего посыпает
    запрос по сгенерированному URL-адресу, учитывая ограничения на количество запросов к серверам
    Pubchem.
    :param start: Первое значение из запрашиваемых CID.
    :param stop: Последнее значение из запрашиваемых CID.
    :param maxsize: Максимальное число идентификаторов в одном запросе, по умолчанию равно 100.
    :return: итератор по записям из базы данных Pubchem - 'Compound'.
    """
    tags = (
        PropertyTags.MOLECULAR_FORMULA,
        PropertyTags.MOLECULAR_WEIGHT,
        PropertyTags.CANONICAL_SMILES,
        PropertyTags.INCHI,
        PropertyTags.IUPAC_NAME,
        PropertyTags.XLOGP,
        PropertyTags.H_BOND_DONOR_COUNT,
        PropertyTags.H_BOND_ACCEPTOR_COUNT,
        PropertyTags.ROTATABLE_BOND_COUNT,
        PropertyTags.ATOM_STEREO_COUNT,
        PropertyTags.BOND_STEREO_COUNT,
        PropertyTags.VOLUME_3D
    )
    d = {
        "domain": Domain.COMPOUND,
        "namespace_prefix": NamespCmpd.CID,
        "namespace_suffix": None,
        "operation": OperationComplex.PROPERTY,
        "tags": tags,
        "output": Out.JSON,
    }

    chunks = chunked(generate_ids(start, stop), maxsize)
    for chunk in delay_iterations(chunks):
        try:
            url = url_builder(chunk, **d)
            logger.debug("Делаю запрос по URL: {}", url)
            res = request_property_data_json(url)
        except requests.HTTPError:
            logger.error("Ошибка при выполнении запроса.", exc_info=True)
            break
        except BadDomainError:
            logger.error("В данной версии сервиса поиск возможен только по базе данных 'Compound'")
        except BadNamespaceError:
            logger.error("Пространство имен поиска по базе данных 'Compound' задано некорректно")
        except BadOperationError:
            logger.error("Ошибка при составлении операции")
        else:
            logger.debug("Пришел ответ: {}", res)
            for rec in res:
                yield rec


if __name__ == "__main__":
    execute_requests(1, 100, 100)