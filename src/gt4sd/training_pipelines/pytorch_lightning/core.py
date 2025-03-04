#
# MIT License
#
# Copyright (c) 2022 GT4SD team
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
"""PyTorch Lightning training utilities."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import sentencepiece as _sentencepiece
from pytorch_lightning import LightningDataModule, LightningModule, Trainer
from pytorch_lightning.callbacks.base import Callback
from pytorch_lightning.callbacks.early_stopping import EarlyStopping
from pytorch_lightning.callbacks.model_checkpoint import ModelCheckpoint

from ..core import TrainingPipeline, TrainingPipelineArguments

# sentencepiece has to be loaded before lightning to avoid segfaults
_sentencepiece

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class PyTorchLightningTrainingPipeline(TrainingPipeline):
    """PyTorch lightining training pipelines."""

    def train(  # type: ignore
        self,
        pl_trainer_args: Dict[str, Any],
        model_args: Dict[str, Union[float, str, int]],
        dataset_args: Dict[str, Union[float, str, int]],
    ) -> None:
        """Generic training function for PyTorch Lightning-based training.

        Args:
            pl_trainer_args: pytorch lightning trainer arguments passed to the configuration.
            model_args: model arguments passed to the configuration.
            dataset_args: dataset arguments passed to the configuration.
        """

        logger.info(f"Trainer arguments: {pl_trainer_args}")

        if pl_trainer_args[
            "resume_from_checkpoint"
        ] is not None and not pl_trainer_args["resume_from_checkpoint"].endswith(
            ".ckpt"
        ):
            pl_trainer_args["resume_from_checkpoint"] = None

        pl_trainer_args["callbacks"] = {
            "model_checkpoint_callback": {
                "monitor": pl_trainer_args["monitor"],
                "save_top_k": pl_trainer_args["save_top_k"],
                "mode": pl_trainer_args["mode"],
                "every_n_train_steps": pl_trainer_args["every_n_train_steps"],
                "save_last": pl_trainer_args["save_last"],
            }
        }

        del (
            pl_trainer_args["monitor"],
            pl_trainer_args["save_top_k"],
            pl_trainer_args["mode"],
            pl_trainer_args["every_n_train_steps"],
            pl_trainer_args["save_last"],
        )

        pl_trainer_args["callbacks"] = self.add_callbacks(pl_trainer_args["callbacks"])

        trainer = Trainer(**pl_trainer_args)
        data_module, model_module = self.get_data_and_model_modules(
            model_args, dataset_args
        )
        trainer.fit(model_module, data_module)

    def get_data_and_model_modules(
        self,
        model_args: Dict[str, Union[float, str, int]],
        dataset_args: Dict[str, Union[float, str, int]],
    ) -> Tuple[LightningDataModule, LightningModule]:
        """Get data and model modules for training.

        Args:
            model_args: model arguments passed to the configuration.
            dataset_args: dataset arguments passed to the configuration.

        Returns:
            the data and model modules.
        """
        raise NotImplementedError(
            "Can't get data and model modules for an abstract training pipeline."
        )

    def add_callbacks(self, callback_args: Dict[str, Any]) -> List[Callback]:
        """Create the requested callbacks for training.

        Args:
            callback_args: callback arguments passed to the configuration.

        Returns:
            list of pytorch lightning callbacks.
        """

        callbacks: List[Callback] = []
        if "early_stopping_callback" in callback_args:
            callbacks.append(EarlyStopping(**callback_args["early_stopping_callback"]))

        if "model_checkpoint_callback" in callback_args:
            callbacks.append(
                ModelCheckpoint(**callback_args["model_checkpoint_callback"])
            )

        return callbacks


@dataclass
class PytorchLightningTrainingArguments(TrainingPipelineArguments):
    """
    Arguments related to pytorch lightning trainer.
    """

    __name__ = "pl_trainer_args"

    accelerator: Union[str, None] = field(
        default="ddp", metadata={"help": "Accelerator type."}
    )
    accumulate_grad_batches: int = field(
        default=1,
        metadata={
            "help": "Accumulates grads every k batches or as set up in the dict."
        },
    )
    val_check_interval: int = field(
        default=5000, metadata={"help": " How often to check the validation set."}
    )
    default_root_dir: Union[str, None] = field(
        default=None, metadata={"help": "Default path for logs and output."}
    )

    gradient_clip_val: float = field(
        default=0.0, metadata={"help": "Gradient clipping value."}
    )
    limit_val_batches: int = field(
        default=500, metadata={"help": "How much of validation dataset to check."}
    )
    log_every_n_steps: int = field(
        default=500, metadata={"help": "How often to log within steps."}
    )
    max_epochs: int = field(
        default=3,
        metadata={"help": "Stop training once this number of epochs is reached."},
    )
    resume_from_checkpoint: Union[str, None] = field(
        default=None,
        metadata={"help": "Path/URL of the checkpoint from which training is resumed."},
    )
    gpus: Union[int, None] = field(
        default=-1,
        metadata={"help": "Number of gpus to train on."},
    )
    monitor: Union[str, None] = field(
        default=None,
        metadata={"help": "Quantity to monitor in order to store a checkpoint."},
    )
    save_last: bool = field(
        default=True,
        metadata={
            "help": "When True, always saves the model at the end of the epoch to a file last.ckpt"
        },
    )
    save_top_k: Optional[int] = field(
        default=None,
        metadata={
            "help": "The best k models according to the quantity monitored will be saved."
        },
    )
    mode: str = field(
        default="min",
        metadata={"help": "Quantity to monitor in order to store a checkpoint."},
    )
    every_n_train_steps: Union[int, None] = field(
        default=None,
        metadata={"help": "Number of training steps between checkpoints."},
    )
