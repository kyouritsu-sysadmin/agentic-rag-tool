from kyoritsu_backend.core.errors import ApplicationError


class ModelCatalog:
    def __init__(self, models, settings):
        self.models, self.settings = models, settings

    def list(self):
        return {
            "models": [
                dict(
                    id="default",
                    name="[TEST] Fixture model"
                    if self.settings.model_backend == "test"
                    else self.settings.answer_model,
                    streaming=True,
                    attachments=False,
                    loaded=self.models.loaded,
                )
            ]
        }

    async def warmup(self, principal):
        if not principal.admin:
            raise ApplicationError(403, "Administrator required")
        await self.models.call(self.models._load)
        return {"loaded": True}
