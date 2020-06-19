import logging
import os
from pathlib import Path

import numpy as np
import pytorch_lightning as pl
import torch
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.utilities import rank_zero_only


def count_trainable_parameters(model):
    model_parameters = filter(lambda p: p.requires_grad, model.parameters())
    params = sum([np.prod(p.size()) for p in model_parameters])
    return params


logger = logging.getLogger(__name__)


class Seq2SeqLoggingCallback(pl.Callback):
    @rank_zero_only
    def _write_logs(
        self, trainer: pl.Trainer, pl_module: pl.LightningModule, type_path: str, save_generations=True
    ) -> None:
        logger.info(f"***** {type_path} results *****")
        metrics = trainer.callback_metrics
        trainer.logger.log_metrics({k: v for k, v in metrics.items() if k not in ["log", "progress_bar", "preds"]})
        # Log results
        od = Path(pl_module.hparams.output_dir)
        if type_path == "test":
            output_val_results_file = od / f"{type_path}_results.txt"
        else:
            output_val_results_file = od / f"{type_path}_{trainer.global_step}_results.txt"

        with open(output_val_results_file, "a+") as writer:
            for key in sorted(metrics):
                if key in ["log", "progress_bar", "preds"]:
                    continue
                val = metrics[key]
                if isinstance(val, torch.Tensor):
                    val = val.item()
                msg = f"{key}: {val:.6f}\n"
                # logger.info(msg)
                writer.write(msg)

        if not save_generations:
            return
        if type_path == "val":
            generations_file = od / f"{type_path}_generations_{trainer.global_step}.txt"
        else:
            generations_file = od / f"{type_path}_generations.txt"
        if "preds" in metrics:
            content = "\n".join(metrics["preds"])
            generations_file.open("w+").write(content)

    @rank_zero_only
    def on_train_start(self, trainer, pl_module):
        try:
            npars = pl_module.model.model.num_parameters()
        except AttributeError:
            npars = pl_module.model.num_parameters()

        n_trainable_pars = count_trainable_parameters(pl_module)
        trainer.logger.log_metrics({"n_params": npars, "mp": npars / 1e6, "grad_mp": n_trainable_pars / 1e6})

    @rank_zero_only
    def on_validation_end(self, trainer: pl.Trainer, pl_module: pl.LightningModule):
        return self._write_logs(trainer, pl_module, "val")

    @rank_zero_only
    def on_test_end(self, trainer: pl.Trainer, pl_module: pl.LightningModule):
        return self._write_logs(trainer, pl_module, "test")


def get_rouge2_checkpoint_callback(output_dir):
    checkpoint_callback = ModelCheckpoint(
        filepath=os.path.join(output_dir, "{val_avg_rouge2:.4f}-{step_count}"),
        monitor="val_rouge",
        mode="max",
        save_top_k=1,
        save_weights_only=False,
        period=0,  # everytime val is run, save a checkpoint
    )
    return checkpoint_callback