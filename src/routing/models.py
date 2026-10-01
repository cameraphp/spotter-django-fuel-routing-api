
from django.db import models


class FuelPriceRecord(models.Model):
    opis_truckstop_id = models.IntegerField(db_index=True)
    truckstop_name = models.CharField(max_length=255)
    address = models.CharField(max_length=511)
    city = models.CharField(max_length=255)
    state = models.CharField(max_length=16, db_index=True)
    rack_id = models.CharField(max_length=63)
    retail_price = models.DecimalField(max_digits=10, decimal_places=4, db_index=True)

    natural_key_hash = models.CharField(max_length=64, db_index=True)
    source_row_id = models.IntegerField()
    source_file = models.CharField(max_length=255)

    latitude = models.DecimalField(
        max_digits=12, decimal_places=7, null=True, blank=True, db_index=True
    )
    longitude = models.DecimalField(
        max_digits=12, decimal_places=7, null=True, blank=True, db_index=True
    )

    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('natural_key_hash', 'source_row_id', 'source_file')]
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['natural_key_hash', 'retail_price']),
        ]

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class GeocodeCache(models.Model):
    cache_key = models.CharField(max_length=64, unique=True, db_index=True)
    query_type = models.CharField(max_length=32)
    query_input = models.TextField()

    latitude = models.DecimalField(max_digits=12, decimal_places=7, null=True)
    longitude = models.DecimalField(max_digits=12, decimal_places=7, null=True)
    display_name = models.TextField(null=True)
    country_code = models.CharField(max_length=4, null=True)
    state_code = models.CharField(max_length=4, null=True)

    raw_json = models.TextField(null=True)
    resolved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)


class RouteCache(models.Model):
    cache_key = models.CharField(max_length=64, unique=True, db_index=True)

    start_latitude = models.DecimalField(max_digits=12, decimal_places=7)
    start_longitude = models.DecimalField(max_digits=12, decimal_places=7)
    end_latitude = models.DecimalField(max_digits=12, decimal_places=7)
    end_longitude = models.DecimalField(max_digits=12, decimal_places=7)

    distance_miles = models.DecimalField(max_digits=14, decimal_places=4)
    geometry_geojson = models.TextField()
    duration_seconds = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

    resolved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
