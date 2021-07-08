import pathlib
from typing import Any, Dict, List

import click

from molecad.data.core.db import drop_collection, upload_data
from molecad.data.core.downloader import execute_request
from molecad.data.core.utils import check_dir, chunked, converter, file_name, read, write


@click.group(
    help="Утилита для извлечения информации с серверов Pubchem и ее записи в файлы или в "
    "локальную базу данных с помощью интерфейса командной строки."
)
def cli():
    pass


@click.command(
    help="Выполняет запрос к серверу Pubchem, извлекает данные из ответа сервера и пишет их в файл"
)
@click.option(
    "--out-dir",
    required=True,
    type=pathlib.Path,
    help="Путь до output-директории, в которую будет записан JSON-файл",
)
@click.option(
    "--start", default=1, required=True, type=int, help="Первое значение из запрашиваемых CID"
)
@click.option(
    "--stop", default=201, required=True, type=int, help="Последнее значение из запрашиваемых CID"
)
@click.option(
    "--size",
    default=100,
    required=True,
    type=int,
    help="Максимальное число идентификаторов в одном запросе",
)
def fetch(out_dir: pathlib.Path, start: int, stop: int, size: int) -> None:
    data = execute_request(start, stop, size)
    check_dir(out_dir)
    file = file_name(out_dir)
    write(file, list(data.values()))


@click.command(
    help="Разрезает большой JSON на чанки меньшего размера для последующей загрузки в "
    "MongoDB, что необходимо из-за внутренних ограничений MongoDB на количество "
    "документов, загружаемых за один раз одним файлом."
)
@click.option("--file", required=True, type=pathlib.Path, help="Путь до большого JSON-файла")
@click.option(
    "--f-dir",
    required=True,
    type=pathlib.Path,
    help="Путь до директории, в которую будут записаны созданные chunked-файлы",
)
@click.option(
    "--size", default=1000, type=int, help="Максимальное число элементов в одном chunked-файле"
)
def split(file: pathlib.Path, f_dir: pathlib.Path, size: int) -> None:
    check_dir(f_dir)
    data: List[Dict[str, Any]] = converter(read(file))
    click.echo(f"Открываю файл {file}")
    for i, chunk in enumerate(chunked(data, size), start=1):
        ch_path = file_name(f_dir)
        write(ch_path, chunk)
        click.echo(f"Записываю в файл {ch_path}")


@click.command(help="Загружает chunked-файлы из указанной директории в локальную базу MongoDB.")
@click.option(
    "--f-dir",
    required=True,
    type=pathlib.Path,
    help="Путь до директории, содержащей chunked-файлы, содержимое каждого из которых "
    "представляет собой список, длинной до 100000 элементов - ограничение MongoDB",
)
@click.option(
    "--collection",
    required=True,
    type=str,
    help="Название коллекции MongoDB, в которую будут загружены файлы.",
)
@click.option(
    "--drop",
    required=True,
    type=bool,
    help="Если значение определено = True, то очищает коллекцию перед импортом документов, "
    "если же = False, то импортирует все документы в указанную коллекцию.",
)
def populate(f_dir: pathlib.Path, collection: str, drop: bool) -> None:
    n = 0
    if drop is True:
        drop_collection(collection)
        click.echo(f"Коллекция {collection} была очищена.")
    click.echo(f"Произвожу импорт из папки {f_dir}")
    for file in f_dir.iterdir():
        click.echo(f"Импортирую файл {file}")
        data: List[Dict[str, Any]] = converter(read(file))
        upload_data(data, collection)
        n += len(data)
    click.echo(f"Загружено {n} документов в коллекцию {collection}")


cli.add_command(fetch)
cli.add_command(split)
cli.add_command(populate)


if __name__ == "__main__":
    cli()
