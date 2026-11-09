"""Pi's upstream adapter with explicit local model limits."""
from harbor.agents.installed.pi import Pi


class LocalPi(Pi):
    def __init__(self, *args, local_context=32768, local_output=8192, **kwargs):
        self.local_context = local_context
        self.local_output = local_output
        super().__init__(*args, **kwargs)

    def _build_custom_models_json(self, access, model_id):
        config = super()._build_custom_models_json(access, model_id)
        if config:
            for provider in config["providers"].values():
                for model in provider["models"]:
                    model.update(contextWindow=self.local_context, maxTokens=self.local_output)
        return config
