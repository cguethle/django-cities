try:
    from django.utils.encoding import force_unicode as force_text
except (NameError, ImportError):
    from django.utils.encoding import force_text

from django.utils.encoding import python_2_unicode_compatible
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import FieldError
from .conf import settings

from logging import getLogger

LOG = getLogger()

__all__ = [
        'Point', 'Country', 'Region', 'Subregion',
        'City', 'District', 'PostalCode', 'AlternativeName', 
]


class PlaceManager(models.GeoManager):
    """
    Custom Manager class for the Place model.
    """

    def nearest_to(self, point, range_in_miles=None):
        """
        Find the place nearest to the point specified.
        :param point: A point in the world (lat, long)
        :type point: django.contrib.gis.geos.point.Point
        :param range_in_miles: Number of miles that the search should be valid within.  If nothing is found within the
            mileage specified, then nearest_to returns a None.  Defaults to None which equates to no distance
            limitation.
        :type range_in_miles: int
        :return: Return the Place nearest to the point.
        :rtype: Place
        """
        place_candidates = self.all()

        if range_in_miles:
            try:
                place_candidates = self.filter(location__distance_lte=(point, D(mi=range_in_miles)))
            except FieldError:
                msg = "Specifying a range_in_miles requires {model} to have a location field to search by.  " \
                      "Implement a meaningful nearest_to func if you need this feature.".format(model=self.model)
                LOG.debug(msg)
                raise FieldError(msg)

        try:
            return place_candidates.distance(point).order_by('distance')[0]
        except TypeError as exc:
            LOG.debug("{model} doesn't appear to be compatible with a distance call.".format(model=self.model))
            raise      # re-raise.
        except IndexError:
            LOG.debug("No Place candidates near to {point}.  Max mileage was {mileage}.".
                      format(point=point, mileage=range_in_miles if range_in_miles else "not considered."))
            return None


@python_2_unicode_compatible
class Place(models.Model):
    name = models.CharField(max_length=200, db_index=True, verbose_name="ascii name")
    slug = models.CharField(max_length=200)
    alt_names = models.ManyToManyField('AlternativeName')

    objects = PlaceManager()

    class Meta:
        abstract = True

    @property
    def hierarchy(self):
        """Get hierarchy, root first"""
        list = self.parent.hierarchy if self.parent else []
        list.append(self)
        return list

    def get_absolute_url(self):
        return "/".join([place.slug for place in self.hierarchy])

    def __str__(self):
        return force_text(self.name)


class CountryManager(PlaceManager):
    """ Manager for Country Model
    """

    def nearest_to(self, point, range_in_miles=None):
        """
        Coutry implementation of Place::nearest_to.
        """
        nearest_city = City.objects.nearest_to(point, range_in_miles)
        """ :type : cities.models.City """

        return nearest_city.country if nearest_city else None


class Country(Place):
    code = models.CharField(max_length=2, db_index=True)
    code3 = models.CharField(max_length=3, db_index=True)
    population = models.IntegerField()
    area = models.IntegerField(null=True)
    currency = models.CharField(max_length=3, null=True)
    currency_name = models.CharField(max_length=50, null=True)
    languages = models.CharField(max_length=250, null=True)
    phone = models.CharField(max_length=20)
    continent = models.CharField(max_length=2)
    tld = models.CharField(max_length=5)
    capital = models.CharField(max_length=100)
    neighbours = models.ManyToManyField("self")

    objects = CountryManager()

    class Meta:
        ordering = ['name']
        verbose_name_plural = "countries"

    @property
    def parent(self):
        return None


class RegionManager(PlaceManager):
    """ Manager for Region Model
    """
    def get_full_index(self, queryset=None):
        """
        Return Regions with their associated full codes in an efficient way.  Since full_code for Region requires an
         additional lookup to country, it is prohibitively expensive to do this without select_related.
        :param queryset: Existing queryset to build on.
        :return:
        """
        queryset = queryset or self.all()
        regions = queryset.select_related('country')

        return {r.full_code(): r for r in regions}

class Region(Place):
    name_std = models.CharField(max_length=200, db_index=True, verbose_name="standard name")
    code = models.CharField(max_length=200, db_index=True)
    country = models.ForeignKey(Country)

    objects = RegionManager()

    @property
    def parent(self):
        return self.country

    def full_code(self):
        return ".".join([self.parent.code, self.code])


class SubregionManager(PlaceManager):
    """ Manager for Region Model
    """
    def get_full_index(self, queryset=None):
        """
        Return Regions with their associated full codes in an efficient way.  Since full_code for Region requires an
         additional lookup to country, it is prohibitively expensive to do this without select_related.
        :param queryset: Existing queryset to build on.
        :return:
        """
        queryset = queryset or self.all()
        subregions = queryset.select_related('region', 'region__country')

        return {r.full_code(): r for r in subregions}


class Subregion(Place):
    name_std = models.CharField(max_length=200, db_index=True, verbose_name="standard name")
    code = models.CharField(max_length=200, db_index=True)
    region = models.ForeignKey(Region)

    objects = SubregionManager()

    @property
    def parent(self):
        return self.region

    def full_code(self):
        return ".".join([self.parent.parent.code, self.parent.code, self.code])


class City(Place):
    name_std = models.CharField(max_length=200, db_index=True, verbose_name="standard name")
    location = models.PointField()
    population = models.IntegerField()
    region = models.ForeignKey(Region, null=True, blank=True)
    subregion = models.ForeignKey(Subregion, null=True, blank=True)
    country = models.ForeignKey(Country)
    elevation = models.IntegerField(null=True)
    kind = models.CharField(max_length=10) # http://www.geonames.org/export/codes.html
    timezone = models.CharField(max_length=40) 

    class Meta:
        verbose_name_plural = "cities"

    @property
    def parent(self):
        return self.region


class District(Place):
    name_std = models.CharField(max_length=200, db_index=True, verbose_name="standard name")
    location = models.PointField()
    population = models.IntegerField()
    city = models.ForeignKey(City)

    @property
    def parent(self):
        return self.city


@python_2_unicode_compatible
class AlternativeName(models.Model):
    name = models.CharField(max_length=256)
    language = models.CharField(max_length=100)
    is_preferred = models.BooleanField(default=False)
    is_short = models.BooleanField(default=False)
    is_colloquial = models.BooleanField(default=False)

    def __str__(self):
        return "%s (%s)" % (force_text(self.name), force_text(self.language))


@python_2_unicode_compatible
class PostalCode(Place):
    code = models.CharField(max_length=20)
    location = models.PointField()

    country = models.ForeignKey(Country, related_name = 'postal_codes')

    # Region names for each admin level, region may not exist in DB
    region_name = models.CharField(max_length=100, db_index=True)
    subregion_name = models.CharField(max_length=100, db_index=True)
    district_name = models.CharField(max_length=100, db_index=True)

    objects = models.GeoManager()

    @property
    def parent(self):
        return self.country

    @property
    def name_full(self):
        """Get full name including hierarchy"""
        return force_text(', '.join(reversed(self.names)))

    @property
    def names(self):
        """Get a hierarchy of non-null names, root first"""
        return [e for e in [
            force_text(self.country),
            force_text(self.region_name),
            force_text(self.subregion_name),
            force_text(self.district_name),
            force_text(self.name),
        ] if e]

    def __str__(self):
        return force_text(self.code)
