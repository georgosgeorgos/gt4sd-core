"""Train module implementation."""

import logging
from argparse import Namespace
from typing import Any, Dict

import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger

from ..arg_parser.parser import parse_arguments_from_config
from ..dataloader.data_module import GranularDataModule
from ..dataloader.dataset import build_dataset_and_architecture
from ..ml.models import AUTOENCODER_ARCHITECTURES
from ..ml.module import GranularModule

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def train_granular(configuration: Dict[str, Any]) -> None:
    """Train a granular given a configuration.
    Args:
        configuration: a configuration dictionary.
    """
    arguments = Namespace(**configuration)
    datasets = []
    architecture_autoencoders = []
    architecture_latent_models = []
    for model in arguments.model_list:
        logger.info(f"dataset preparation for model={model}")
        hparams = configuration[model]
        model_type = hparams["type"].lower()
        dataset, architecture = build_dataset_and_architecture(
            hparams["name"],
            hparams["data_path"],
            hparams["data_file"],
            hparams["dataset_type"],
            hparams["type"],
            hparams,
        )
        datasets.append(dataset)
        if model_type in AUTOENCODER_ARCHITECTURES:
            architecture_autoencoders.append(architecture)
        else:
            architecture_latent_models.append(architecture)
    dm = GranularDataModule(
        datasets,
        batch_size=getattr(arguments, "batch_size", 64),
        validation_split=getattr(arguments, "validation_split", None),
        validation_indices_file=getattr(arguments, "validation_indices_file", None),
        stratified_batch_file=getattr(arguments, "stratified_batch_file", None),
        stratified_value_name=getattr(arguments, "stratified_value_name", None),
        num_workers=getattr(arguments, "num_workers", 1),
    )
    dm.prepare_data()
    module = GranularModule(
        architecture_autoencoders=architecture_autoencoders,
        architecture_latent_models=architecture_latent_models,
        lr=getattr(arguments, "lr", 0.0001),
        test_output_path=getattr(arguments, "test_output_path", "./test"),
    )
    tensorboard_logger = TensorBoardLogger(
        "logs", name=getattr(arguments, "basename", "default")
    )
    checkpoint_callback = ModelCheckpoint(
        every_n_val_epochs=getattr(arguments, "checkpoint_every_n_val_epochs", 5),
        save_top_k=-1,
    )
    trainer = pl.Trainer.from_argparse_args(
        arguments,
        profiler="simple",
        logger=tensorboard_logger,
        auto_lr_find=True,
        log_every_n_steps=getattr(arguments, "trainer_log_every_n_steps", 50),
        callbacks=[checkpoint_callback],
        max_epochs=getattr(arguments, "epoch", 1),
        flush_logs_every_n_steps=getattr(
            arguments, "trainer_flush_logs_every_n_steps", 100
        ),
    )
    trainer.fit(module, dm)


def train_granular_main() -> None:
    """Train a granular module parsing arguments from config and standard input."""
    train_granular(configuration=vars(parse_arguments_from_config()))
