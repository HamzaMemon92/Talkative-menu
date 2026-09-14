from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Importing the models here keeps Alembic's metadata complete while avoiding
# model imports in application modules.
from ainza_restaurant.ai import db_models as ai_models  # noqa: E402,F401
from ainza_restaurant.availability import models as availability_models  # noqa: E402,F401
from ainza_restaurant.billing import models as billing_models  # noqa: E402,F401
from ainza_restaurant.dining import models as dining_models  # noqa: E402,F401
from ainza_restaurant.kitchen import models as kitchen_models  # noqa: E402,F401
from ainza_restaurant.menu import models as menu_models  # noqa: E402,F401
from ainza_restaurant.merchandising import models as merchandising_models  # noqa: E402,F401
from ainza_restaurant.ordering import models as ordering_models  # noqa: E402,F401
from ainza_restaurant.restaurants import models as restaurant_models  # noqa: E402,F401
