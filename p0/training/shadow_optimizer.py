"""Explicit CPU AdamW for the small LoRA adapter, with device gradients intact."""
from __future__ import annotations


def cpu_shadow_adamw(torch, trainable, lr: float, weight_decay: float):
    parameters = tuple(trainable)
    if not parameters or any(parameter.dtype != torch.float32 or not parameter.requires_grad
                             for parameter in parameters):
        raise ValueError("AdamW CPU requiert des paramètres LoRA entraînables en FP32")
    device_types = {parameter.device.type for parameter in parameters}
    if device_types not in ({"mps"}, {"cpu"}):
        raise ValueError("AdamW CPU requiert des paramètres tous sur le même type de périphérique")
    synchronize = torch.mps.synchronize if device_types == {"mps"} else lambda: None

    class CPUShadowAdamW(torch.optim.Optimizer):
        """Expose live parameters for GradScaler; use AdamW on checked CPU copies."""

        def __init__(self):
            super().__init__(parameters, {"lr": lr, "weight_decay": weight_decay})
            self.shadow = tuple(torch.nn.Parameter(parameter.detach().cpu().clone()) for parameter in parameters)
            self.cpu_adamw = torch.optim.AdamW(self.shadow, lr=lr, weight_decay=weight_decay, foreach=False)

        @torch.no_grad()
        def step(self, closure=None):
            if closure is not None or len(self.param_groups) != 1:
                raise ValueError("AdamW CPU : fermeture et groupes supplémentaires non pris en charge")
            group, = self.param_groups
            if (len(group["params"]) != len(parameters)
                    or any(current is not expected for current, expected in zip(group["params"], parameters, strict=True))):
                raise ValueError("AdamW CPU : paramètres de l’adaptateur modifiés en cours d’essai")
            synchronize()
            grads = []
            for parameter, shadow in zip(parameters, self.shadow, strict=True):
                if parameter.grad is None or not torch.equal(parameter.detach().cpu(), shadow):
                    raise ValueError("AdamW CPU : gradient absent ou poids GPU et maître distincts")
                gradient = parameter.grad.detach().cpu().clone()
                if gradient.dtype != torch.float32 or not bool(gradient.isfinite().all()):
                    raise ValueError("AdamW CPU : gradient non fini ou non FP32 après écrêtage")
                grads.append(gradient)
            inner_group, = self.cpu_adamw.param_groups
            inner_group["lr"], inner_group["weight_decay"] = group["lr"], group["weight_decay"]
            for shadow, grad in zip(self.shadow, grads, strict=True):
                shadow.grad = grad
            try:
                self.cpu_adamw.step()
                for shadow, state in self.cpu_adamw.state.items():
                    if not all(tensor.dtype == torch.float32 and bool(tensor.isfinite().all())
                               for tensor in (shadow, state["exp_avg"], state["exp_avg_sq"])):
                        raise ValueError("AdamW CPU : poids maître ou moments non finis ou non FP32")
                # Do not move any candidate back to the student before all CPU state passes.
                for parameter, shadow in zip(parameters, self.shadow, strict=True):
                    parameter.copy_(shadow)
                synchronize()
                if not all(torch.equal(parameter.detach().cpu(), shadow)
                           for parameter, shadow in zip(parameters, self.shadow, strict=True)):
                    raise ValueError("AdamW CPU : poids changés par le transfert retour")
            finally:
                self.cpu_adamw.zero_grad(set_to_none=True)
    return CPUShadowAdamW()
