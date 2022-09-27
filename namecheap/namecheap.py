"""
Python Namecheap API

**Copyright**::

    +===================================================================+
    |                        © 2020 Privex Inc.                         |
    |                      https://www.privex.io                        |
    +===================================================================+
    |                                                                   |
    |            Python Namecheap API                                   |
    |                                                                   |
    |            Repo: https://github.com/Privex/PyNamecheap            |
    |            PyPi Package: privex-namecheap                         |
    |                                                                   |
    |            License: X11 / MIT                                     |
    |                                                                   |
    |            Core Developer(s):                                     |
    |                                                                   |
    |              (+)  Chris (@someguy123) [Privex]                    |
    |              (+)  Kale (@kryogenic) [Privex]                      |
    |                                                                   |
    +===================================================================+

"""
import copy
import sys
import time
import requests  # pip install requests
import logging
from typing import Dict, Generator, Iterable, List, Optional, Tuple, Type
from xml.etree.ElementTree import fromstring, Element
from privex.helpers import DictObject, Union, cached, empty, empty_if, r_cache
from privex.loghelper import LogHelper

from namecheap.helpers import api_string
from namecheap.exceptions import ApiError
from namecheap.objects import CamelSnakeDictable, CreateDomainResponse, Domain, DomainCheck, DomainDetails, DomainRecord, NamecheapTLD, \
    TLDPrice

__all__ = [
    'NAMECHEAP_ENDPOINTS', 'ENDPOINTS', 'NAMESPACE', 'DEFAULT_ATTEMPTS_COUNT', 'DEFAULT_ATTEMPTS_DELAY', 'Api'
]

log = logging.getLogger(__name__)

inPy3k = sys.version_info[0] == 3

# http://developer.namecheap.com/docs/doku.php?id=overview:2.environments
NAMECHEAP_ENDPOINTS = {
    # To use
    # 1) browse to http://www.sandbox.namecheap.com/
    # 2) create account, my account > manage profile > api access > enable API
    # 3) add your IP address to whitelist
    'sandbox': 'https://api.sandbox.namecheap.com/xml.response',
    'production': 'https://api.namecheap.com/xml.response',
}

# We copy NAMECHEAP_ENDPOINTS to ENDPOINTS, in-case the user edits the current endpoints, and
# needs to restore the original official namecheap endpoints.
ENDPOINTS = dict(NAMECHEAP_ENDPOINTS)
NAMESPACE = "http://api.namecheap.com/xml.response"

# default values for the retry mechanism
DEFAULT_ATTEMPTS_COUNT = 1  # no retries
DEFAULT_ATTEMPTS_DELAY = 0.1  # in seconds


def _clean_arg(a):
    cache_str = ""
    
    if isinstance(a, (str, int)):
        cache_str += f"{a}:"
    elif isinstance(a, (list, tuple, set, Iterable)):
        a = list(a)
        cache_str += ','.join(a) + ':'
    elif isinstance(a, dict):
        for k, v in a.items():
            cache_str += f"{k}={v},"
        cache_str += ':'
    elif isinstance(a, CamelSnakeDictable):
        a = a.to_dict()
        for k, v in a.items():
            cache_str += f"{k}={v},"
        cache_str += ':'
    else:
        cache_str += f"{str(a)}:"
    return cache_str


def _cstr(self: "Api", fname: str, *args, **kwargs) -> str:
    cache_str = f"{self.chprefix}{fname}:"
    for a in args:
        cache_str += _clean_arg(a)

    for k, v in dict(kwargs).items():
        cache_str += f"{k}={_clean_arg(v)}"
    
    return cache_str.strip(':')


# noinspection PyPep8Naming
class Api(object):
    """
    **Basic Usage**::
    
        >>> from namecheap import Api
        >>> api = Api('my_namecheap_username', 'my_api_key', '12.34.56.78', sandbox=True, debug=True)
        >>> doms = list(api.list_domains())
        [
             Domain(id='615025', name='pvxtest.org', user='PrivexExample', created=datetime.datetime(2020, 9, 1, 0, 0),
                    expires=datetime.datetime(2021, 9, 1, 0, 0) is_expired=False, is_locked=False, auto_renew=False,
                    whois_guard='ENABLED', is_premium=False, is_our_dns=True),
             Domain(id='615026', name='pvxtest2.org', user='PrivexExample', created=datetime.datetime(2020, 9, 1, 0, 0),
                    expires=datetime.datetime(2021, 9, 1, 0, 0) is_expired=False, is_locked=False, auto_renew=False,
                    whois_guard='ENABLED', is_premium=False, is_our_dns=True)
        ]
        >>> api.renew_domain('pvxtest.org')
        >>> api.get_nameservers('example.org')
        ['dns1.registrar-servers.com', 'dns2.registrar-servers.com']
        >>> api.set_nameservers('example.com', 'ns1.privex.io', 'ns2.privex.io', 'ns3.privex.io')
        >>> api.get_nameservers('example.org')
        ['ns1.privex.io', 'ns2.privex.io', 'ns3.privex.io']
        
    **Caching**
    
    Most methods which **retrieve/get** data from the Namecheap API use :func:`.r_cache` to automatically cache
    their result with the :mod:`privex.helpers.cache` Cache Abstraction Layer.
    
    Caching works out of the box, without any need for cache servers such as **Redis** or **Memcached**. This is
    because by default, Privex's cache layer defaults to :class:`privex.helpers.cache.MemoryCache.MemoryCache` ,
    which is a caching adapter that simply stores cache data in the memory of your Python application, using a
    dictionary contained within a global class attribute.
    
    However, for the best caching experience, it's strongly recommended to install **Redis**:
    
      * Install **Redis Server** from your OS's package manager, e.g. ``apt install redis-server``
        Redis comes pre-configured to work out of the box, you do not need to configure it. The default
        Redis configs are secure and perfectly fine for most uses.
    
      * Install the Python package ``privex-helpers[cache]`` to install all dependencies for using the cache abstraction layer
        with third party caching servers such as Redis. e.g. ``pip3 install -U 'privex-helpers[cache]'``
    
      * Set the global Privex Helpers cache adapter to :class:`privex.helpers.cache.RedisCache.RedisCache`
        using the :func:`privex.helpers.cache.adapter_set` function.
    
    Example for setting the cache adapter to RedisCache::
        
        >>> from privex.helpers.cache import adapter_set, RedisCache
        >>> adapter_set(RedisCache())
    
    **Example of caching**
    
    For example, if you run :meth:`.domains_getInfo` for the same domain - two times in a row, the first call
    will take a few seconds, while the second call will return instantaneously::
    
        >>> from namecheap import Api
        >>> api = Api('user', 'key', '12.34.56.78')
        >>> dom = api.domains_getInfo('pvxtest.org')    # Takes a few seconds
        >>> dom2 = api.domains_getInfo('pvxtest.org')   # Returns instantly
    
    **Bypassing / temporarily disabling caching for one method call**
    
    Sometimes, you may need to temporarily bypass this caching, for example, getting information about a domain
    after you've *just* updated it a few seconds ago.
    
    Thankfully, :func:`.r_cache` has a feature which allows you to bypass caching simply by specifying
    the keyword argument ``r_cache=False`` when calling a cached function::
    
        >>> dom = api.domains_getInfo('pvxtest.org')                    # Takes a few seconds (domain data isn't cached yet)
        >>> dom2 = api.domains_getInfo('pvxtest.org')                   # Returns instantly (from cache)
        >>> dom3 = api.domains_getInfo('pvxtest.org', r_cache=False)    # Takes a few seconds (bypassing cache)
        >>> dom4 = api.domains_getInfo('pvxtest.org')                   # Returns instantly (from cache)
    
    """
    ENDPOINTS = ENDPOINTS
    
    # Follows API spec capitalization in variable names for consistency.
    def __init__(self, ApiUser, ApiKey, ClientIP, UserName=None, sandbox=False, debug=False, proxies=None,
                 attempts_count=DEFAULT_ATTEMPTS_COUNT, attempts_delay=DEFAULT_ATTEMPTS_DELAY,
                 **kwargs):
        self.ApiUser = ApiUser
        self.ApiKey = ApiKey
        self.ClientIP = ClientIP
        self.UserName = empty_if(UserName, ApiUser)
        self.sandbox = sandbox
        self.endpoint = kwargs.pop('endpoint', ENDPOINTS['sandbox' if sandbox else 'production'])
        self.debug = debug
        self.payload_limit = 10  # After hitting this lenght limit script will move payload from POST params to POST data
        self.attempts_count = attempts_count
        self.attempts_delay = attempts_delay
        self.proxies = proxies

        if kwargs.get('add_logger', True):
            lh = LogHelper('namecheap', handler_level=logging.DEBUG if debug else logging.WARNING)
            lh.add_console_handler()

    @staticmethod
    def set_endpoint(endpoint: str, url: str):
        """
        Update one of the global endpoint URLs.
        
        This is useful for organisations / persons who have a complex network, and to avoid having to whitelist many
        different IPs, they have domain(s) which proxy to the namecheap production/sandbox API via a whitelisted IP.
        
        Example::
        
            >>> from namecheap import Api
            >>> Api.set_endpoint('production', 'https://namecheap-api.somecorp.net')
            >>> Api.set_endpoint('sandbox', 'https://namecheap-sandbox-api.somecorp.net')
        
        :param str endpoint:  The name of the endpoint to set. As of now, two endpoint names are valid: ``production`` and ``sandbox``
        :param str url:       The URL to set the endpoint to.
        """
        if endpoint not in ENDPOINTS:
            raise AttributeError(
                f"Invalid endpoint name. Valid endpoint names are: {', '.join(ENDPOINTS.keys())}"
            )
        ENDPOINTS[endpoint] = url
        Api.ENDPOINTS[endpoint] = url
        return ENDPOINTS

    # https://www.namecheap.com/support/api/methods/domains/create.aspx
    def domains_create(
        self,
        DomainName: str, FirstName: str, LastName: str,
        Address1: str, City: str, StateProvince: str, PostalCode: str, Country: str, Phone: str,
        EmailAddress: str, Address2: str = None, years: int = 1, WhoisGuard: bool = False,
        OrganizationName: str = None, JobTitle: str = None, PromotionCode: str = None,
        Nameservers: Union[str, list] = None, **user_payload
    ) -> CreateDomainResponse:
        """
        Registers a domain name with the given contact info.
        Example of a working phone number: +81.123123123

        For simplicity assumes one person acts as all contact types.
        
        If you're registering a domain as a company/organisation, specify the company name in ``OrganizationName``,
        and specify the job role of the person named in ``FirstName`` / ``LastName`` in ``JobTitle``
        e.g. ``domains_create(FirstName='John', LastName='Doe', OrganizationName='ExampleCorp', JobTitle='Chief Technical Officer')``
        
        **Example Usage**::
        
            >>> api = Api('user', 'key', '12.34.56.78')
            >>> res = api.domains_create(
            ...     DomainName = 'somecooldomain.com',
            ...     FirstName = 'Jack',
            ...     LastName = 'Trotter',
            ...     Address1 = 'Ridiculously Big Mansion, Yellow Brick Road',
            ...     City = 'Tokushima',
            ...     StateProvince = 'Tokushima',
            ...     PostalCode = '771-0144',
            ...     Country = 'Japan',
            ...     Phone = '+81.123123123',
            ...     EmailAddress = 'jack.trotter@example.com'
            ... )
            >>> print(res)
            {
                'Domain': 'somecooldomain.com', 'Registered': 'true', 'ChargedAmount': '12.1600',
                'DomainID': '615026', 'OrderID': '2139371', 'TransactionID': '4139125',
                'WhoisguardEnable': 'true', 'FreePositiveSSL': 'false', 'NonRealTimeDomain': 'false'
            }
        
        **Automatically set nameservers on purchase**::
            
            >>> # For readability, we're not including the required contact information for these calls
            >>> # You can specify Nameservers as either a list [] of nameservers as strings
            >>> api.domains_create('anotherdomain.com', Nameservers=['ns1.example.com', 'ns2.example.com', 'ns3.example.com'])
            >>> # OR you can specify them as a comma separated string - it's up to your preference
            >>> # There is no difference in result whether you specify nameservers as a list or string
            >>> api.domains_create('anotherdomain.com', Nameservers='ns1.example.com,ns2.example.com,ns3.example.com')
        
        :raises ApiError: When ``<Error />`` in the result is non-empty.
        :return dict DomainCreateResult: The attributes of the result's ``<DomainCreateResult />`` as a dictionary
        """

        contact_types = ['Registrant', 'Tech', 'Admin', 'AuxBilling']

        extra_payload = {
            'DomainName': DomainName,
            'years': years
        }

        if WhoisGuard:    extra_payload.update(dict(AddFreeWhoisguard='yes', WGEnabled='yes'))
        if PromotionCode: extra_payload['PromotionCode'] = PromotionCode
        
        if Nameservers:
            if isinstance(Nameservers, (list, set, tuple)):
                Nameservers = ','.join(Nameservers)
            extra_payload['Nameservers'] = Nameservers
        
        for contact_type in contact_types:
            extra_payload.update({
                f'{contact_type}FirstName':     FirstName,
                f'{contact_type}LastName':      LastName,
                f'{contact_type}Address1':      Address1,
                f'{contact_type}City':          City,
                f'{contact_type}StateProvince': StateProvince,
                f'{contact_type}PostalCode':    PostalCode,
                f'{contact_type}Country':       Country,
                f'{contact_type}Phone':         Phone,
                f'{contact_type}EmailAddress':  EmailAddress,
            })
            if Address2: extra_payload[f'{contact_type}Address2'] = Address2
            if OrganizationName: extra_payload[f'{contact_type}OrganizationName'] = OrganizationName
            if JobTitle: extra_payload[f'{contact_type}JobTitle'] = JobTitle
        
        # Merge in any user payload key:value's on top of our generated payload dictionary
        extra_payload = {**extra_payload, **user_payload}
        
        xml = self.call('namecheap.domains.create', extra_payload)
        res = self.get_element_dict(xml, 'DomainCreateResult')
        self.clear_cache_domain(DomainName)
        return CreateDomainResponse.from_dict(res)

    register_domain = domains_create

    @staticmethod
    def get_element(element, element_name):
        # type: (Element, str) -> Element
        return element.find(f'.//{{{NAMESPACE}}}{element_name}')

    @staticmethod
    def get_element_dict(element: Element, element_name: str, fail: bool = False) -> Optional[dict]:
        """Find ``<element_name a=1 b=2>contents</element_name>`` inside ``element`` and return ``{'a': 1, 'b': 2}``"""
        try:
            return dict(Api.get_element(element, element_name).items())
        except Exception as e:
            log.warning(
                "Error while getting element attrs as dict. Element: %s || Name: %s || Err: %s - %s",
                element, element_name, type(e), str(e)
            )
            if fail:
                raise e
            return None
    
    @staticmethod
    def get_element_text(element: Element, element_name: str, fail: bool = False, strip: bool = True) -> Optional[str]:
        """Find ``<element_name a=1 b=2>contents</element_name>`` inside ``element`` and return ``contents``"""
        try:
            t = Api.get_element(element, element_name).text
            return t.strip() if strip else t
        except Exception as e:
            log.warning(
                "Error while getting element contents as str. Element: %s || Name: %s || Err: %s - %s",
                element, element_name, type(e), str(e)
            )
            if fail:
                raise e
            return None

    @staticmethod
    def get_element_content_keypairs(
            element: Element, element_name: str, fail: bool = False, strip: bool = True
    ) -> Optional[List[Tuple[str, str]]]:
        """
        Find ``<element_name a=1><hello>world</hello><lorem>ipsum</lorem</element_name>`` inside ``element``
        and return ``[('hello', 'world'), ('lorem', 'ipsum')]``
        """
        try:
            el = Api.get_element(element, element_name)
            res = [
                (
                    v.tag.replace(f"{{{NAMESPACE}}}", ""),
                    v.text.strip() if strip else v.text
                ) for v in el if v.text is not None
            ]
            
            return res
        except Exception as e:
            log.warning(
                "Error while getting element contents as tuple pairs. Element: %s || Name: %s || Err: %s - %s",
                element, element_name, type(e), str(e)
            )
            if fail:
                raise e
            return None

    @staticmethod
    def get_element_content_dict(
            element: Element, element_name: str, fail: bool = False, strip: bool = True
    ) -> Optional[Dict[str, str]]:
        """
        Find ``<element_name a=1><hello>world</hello><lorem>ipsum</lorem</element_name>`` inside ``element``
        and return ``{'hello': 'world', 'lorem': 'ipsum'}``
        """
        try:
            kv = Api.get_element_content_keypairs(element, element_name, fail=fail, strip=strip)
            if kv is None:
                if fail:
                    raise ValueError("result from get_element_content_keypairs was None")
                return None
            
            if empty(kv, itr=True):
                return {}
        
            return dict(kv)
        except Exception as e:
            log.warning(
                "Error while getting element contents as a dictionary. Element: %s || Name: %s || Err: %s - %s",
                element, element_name, type(e), str(e)
            )
            if fail:
                raise e
            return None
    
    def _payload(self, Command, extra_payload=None):
        # type: (str, dict) -> (dict, dict)
        """Make dictionary for passing to requests.post"""
        extra_payload = {} if extra_payload is None else extra_payload
        payload = {
            'ApiUser': self.ApiUser,
            'ApiKey': self.ApiKey,
            'UserName': self.UserName,
            'ClientIP': self.ClientIP,
            'Command': Command,
        }
        # Namecheap recommends to use HTTPPOST method when setting more than 10 hostnames
        # https://www.namecheap.com/support/api/methods/domains-dns/set-hosts.aspx
        if len(extra_payload) < self.payload_limit:
            payload.update(extra_payload)
            extra_payload = {}
        return payload, extra_payload

    def fetch_xml(self, payload: dict, extra_payload: dict = None) -> Element:
        """Make network call and return parsed XML element"""
        attempts_left = self.attempts_count
        while attempts_left > 0:
            if extra_payload:
                r = requests.post(self.endpoint, params=payload, data=extra_payload, proxies=self.proxies)
            else:
                r = requests.post(self.endpoint, params=payload, proxies=self.proxies)
            if 200 <= r.status_code <= 299:
                break
            if attempts_left <= 1:
                # Here we provide 1 error code which is not present in official docs
                raise ApiError('1', 'Did not receive 200 (Ok) response')
            log.debug(f'Received status {r.status_code} ... retrying ...')
            time.sleep(self.attempts_delay)
            attempts_left -= 1

        log.debug("--- Request ---")
        log.debug(r.url)
        log.debug(extra_payload)
        log.debug("--- Response ---")
        log.debug(r.text)
        xml = fromstring(r.text)

        if xml.attrib['Status'] == 'ERROR':
            # Response namespace must be prepended to tag names.
            # xpath = f'.//{{{NAMESPACE}}}Errors/{{{NAMESPACE}}}Error'
            
            # First we try and find a normal <Error /> without namespacing
            error = xml.find('.//Error')
            if error is None:
                # If we can't find a non-namespaced error, then try and find a namespaced error.
                error = self.get_element(xml, 'Error')
            # If we still can't find the error tag, give up and raise an unknown error.
            if error is None:
                raise ApiError(0, "An unknown error has occurred - cannot locate Error XML element to display correct message.")
            # Otherwise, raise an error with the appropriate error number and text.
            raise ApiError(error.attrib['Number'], error.text)

        return xml

    # For backwards compatibility with <=0.0.3 - we alias _fetch_xml to fetch_xml
    _fetch_xml = fetch_xml

    def call(self, Command: str, extra_payload: dict = None) -> Element:
        """Call an API command"""
        extra_payload = {} if extra_payload is None else extra_payload
        payload, extra_payload = self._payload(Command, extra_payload)
        log.debug("Api.call - Command: %s || payload: %s || extra_payload: %s", Command, payload, extra_payload)
        xml = self.fetch_xml(payload, extra_payload)
        return xml

    # For backwards compatibility with <=0.0.3 - we alias _call to call
    _call = call

    class LazyGetListIterator(object):
        """When listing domain names, only one page is returned
        initially. The list needs to be paged through to see all.
        This iterator gets the next page when necessary."""

        # @r_cache(lambda self: , 60)
        def _get_more_results(self):
            xml = self.api.fetch_xml(self.payload)
            xpath = f'.//{{{NAMESPACE}}}CommandResponse/{{{NAMESPACE}}}DomainGetListResult/{{{NAMESPACE}}}Domain'
            domains = xml.findall(xpath)
            return [domain.attrib for domain in domains]
        
        def get_more_results(self):
            for attr in self._get_more_results():
                self.results.append(attr)
            self.payload['Page'] += 1

        @property
        def next_result(self):
            if self.dtclass:
                return self.dtclass.from_dict(self.results[self.i])
            return self.results[self.i]

        def __init__(self, api, payload, dtclass: Type[CamelSnakeDictable] = None, cache_key='getList', use_cache=True):
            self.api = api
            self.payload = payload
            # self.orig_payload = dict(copy.deepcopy(payload))
            self.cache_key = cache_key
            self.use_cache = use_cache
            self.has_cache = False
            self.dtclass = dtclass
            self.results = []
            self.i = -1
            results_cached = cached.get(self.cache_key)
            if self.use_cache and not empty(results_cached, True, True):
                log.debug("Domain list is cached in key: %s", self.cache_key)
                log.debug("Setting self.results to cached data: %s", results_cached)
                self.results = results_cached
                self.has_cache = True
            else:
                log.debug("Domain list is NOT cached. Querying namecheap API.")

        def __iter__(self):
            return self

        def __next__(self):
            self.i += 1
            if self.has_cache:
                if self.i >= len(self.results):
                    log.debug("End of cached results.")
                    raise StopIteration
                log.debug("Returning result %s from cache: %s", self.i, self.next_result)
                return self.next_result

            if self.i >= len(self.results):
                log.debug("Loading next page of domain list results from API")
                self.get_more_results()

            if self.i >= len(self.results):
                log.debug("Reached end of domain list results. Storing results into cache key %s - results: %s", self.cache_key, self.results)
                cached.set(self.cache_key, self.results, 60)
                raise StopIteration
            return self.next_result
            
        next = __next__

    # https://www.namecheap.com/support/api/methods/domains-dns/set-default.aspx
    def domains_dns_setDefault(self, domain: str) -> dict:
        """
        Sets domain to use Namecheap's default DNS servers.
        
        Required for free services like Host record management, URL forwarding, email forwarding,
        dynamic dns and other value added services.
        
        :param str domain: The domain to set default nameservers for
        :return dict res: The response from the API call
        """
        sld, tld = domain.split(".")
        xml = self.call("namecheap.domains.dns.setDefault", dict(SLD=sld, TLD=tld))
        self.clear_cache_domain(domain)
        return self.get_element_dict(xml, 'DomainDNSSetDefaultResult')
    
    @property
    def chprefix(self):
        return f"pync:{self.UserName}:{'sbox' if self.sandbox else 'prod'}:"

    @r_cache(lambda self, **user_payload: _cstr(self, 'getTldList', **user_payload), 600)
    def domains_getTldList(self, **user_payload) -> Dict[str, NamecheapTLD]:
        xml = self.call('namecheap.domains.gettldlist', dict(user_payload))
        tld_res = {}
        tlds = self.get_element(xml, 'Tlds')
        for t in tlds:
            attribs = dict(t.items())
            name = attribs['Name']
            attribs['Description'] = t.text
            tld_cats = []
            if len(t) > 0:
                for cwrap in t:   # type: Element
                    if not cwrap.tag.endswith('Categories') or len(cwrap) < 1:
                        continue
                    for tlcat in cwrap:   # type: Element
                        if not tlcat.tag.endswith('TldCategory'): continue
                        tld_cats.append(dict(tlcat.items()))
                
            attribs['TldCategories'] = tld_cats
            tld_res[name] = NamecheapTLD.from_dict(attribs)
        return tld_res

    @r_cache(lambda self, *args, **kwargs: _cstr(self, 'users_getPricing', *args, **kwargs), 600)
    def users_getPricing(
            self, product_type='DOMAIN', category: str = None, promo_code: str = None, action: str = None,
            name: str = None, **user_payload
    ) -> Dict[str, dict]:
        payload = dict(ProductType=product_type)
        if not empty(category): payload['ProductCategory'] = category
        if not empty(promo_code): payload['PromotionCode'] = promo_code
        if not empty(action): payload['ActionName'] = action
        if not empty(name): payload['ProductName'] = name
        
        xml = self.call('namecheap.users.getPricing', {**payload, **user_payload})
        price_res = {}
        data = self.get_element(xml, 'UserGetPricingResult')
        
        for p in data:   # type: Element
            prod_type = p.attrib['Name']
            p_prod_type = price_res[prod_type] = {}
            
            for c in p:   # type: Element
                cat_name = c.attrib['Name']
                p_cat_name = p_prod_type[cat_name] = {}
                for prod in c:    # type: Element
                    prod_name = prod.attrib['Name']
                    p_prod_name = p_cat_name[prod_name] = [dict(price.items()) for price in prod]
                    
        return price_res

    def get_all_tld_prices(self, years=1, action='REGISTER', **user_payload) -> Union[Dict[str, TLDPrice], DictObject]:
        data = self.users_getPricing(
            product_type='DOMAIN', category='DOMAINS', action=action.upper(), **user_payload
        )
        tld_prices = {}
        for name, tld in data['domains']['register'].items():
            for price in tld:
                if int(price['Duration']) == int(years) and price.get('DurationType', 'YEAR').lower() == 'year':
                    price['Tld'] = name.lower()
                    tld_prices[name.lower()] = TLDPrice.from_dict(price)
        return tld_prices
        
    def get_tld_prices(
            self, *tlds: str, years=1, action='REGISTER', force_dict=False, **user_payload
    ) -> Union[Dict[str, TLDPrice], TLDPrice, DictObject]:
        """
        
        **Example Usage**::
        
            >>> prices = self.get_tld_prices('com', 'org', 'net', 'xyz')
            >>> prices['xyz']
            TLDPrice(
                tld='xyz', duration=1, duration_type='YEAR', price=Decimal('1.0000'), additional_cost=Decimal('0.1800'),
                regular_price=Decimal('10.8800'), regular_additional_cost=Decimal('0.1800'), your_price=Decimal('1.0000'),
                your_additional_cost=Decimal('0.1800'), promotion_price=Decimal('0.0000'),
                coupon_price=Decimal('0.0000'), currency='USD'
            )
            >>> prices['xyz'].price
            Decimal('1.0000')
            >>> prices['xyz'].regular_price
            Decimal('10.8800')
            >>> # Since it returns a DictObject, you can also access keys by attributes
            >>> prices.xyz.total_price
            Decimal('1.1800')
            >>> prices.xyz.total_your_price
            Decimal('1.1800')
            >>> prices.xyz.total_regular_price
            Decimal('11.0600')
            >>> prices.com.total_regular_price
            Decimal('9.0600')
            >>> prices.com.total_your_price
            Decimal('9.0600')
        
        **Single TLD**
        
        When querying for a singular TLD, a :class:`.TLDPrice` will be returned, instead of a :class:`.dict`
        of :class:`.TLDPrice` 's::
        
            >>> cloud = self.get_tld_prices('cloud')
            >>> cloud.total_regular_price
            Decimal('20.0600')
            >>> cloud.total_your_price
            Decimal('5.9800')
        
        If you need to guarantee that it always returns a :class:`.dict` even for single TLDs, you can pass
        ``force_dict=True`` and it will return :class:`.dict`'s for single and multiple TLDs::
        
            >>> prices = self.get_tld_prices('red', force_dict=True)
            >>> prices['red'].total_your_price
            Out[15]: Decimal('4.0600')
            >>> prices['red'].total_regular_price
            Out[16]: Decimal('15.1600')

        :param tlds:
        :param years:
        :param action:
        :param force_dict:
        :param user_payload:
        :return:
        """
        tlds = list(tlds)
        tld_prices = {}
        for t in tlds:
            data = self.users_getPricing(
                product_type='DOMAIN', category='DOMAINS', action=action.upper(), name=t.upper(),
                **user_payload
            )
            for price in data['domains'][action.lower()][t.lower()]:
                if int(price['Duration']) == int(years) and price.get('DurationType', 'YEAR').lower() == 'year':
                    price['Tld'] = t.lower()
                    tld_prices[t.lower()] = TLDPrice.from_dict(price)
        return DictObject(tld_prices) if len(tlds) > 1 or force_dict else tld_prices[tlds[0]]
    
    # https://www.namecheap.com/support/api/methods/domains/check.aspx
    def domains_available(self, *domains, force_dict=False, **user_payload) -> Union[bool, Dict[str, bool]]:
        """Checks the availability of domains.

        For example::
        
            >>> api = Api('user', 'key', '12.34.56.78')
            >>> api.domains_available('taken.com', 'apsdjcpoaskdc.com')
            {
                'taken.com' : False,
                'apsdjcpoaskdc.com' : True
            }
        
        .. NOTE:: When checking a singular domain, a simple :class:`.bool` will be returned,
                  unless you pass ``force_dict=True`` to guarantee a :class:`.dict`
        
        Single domain example::
        
            >>> api.domains_available('taken.com')
            False
            >>> api.domains_available('apsdjcpoaskdc.com')
            True
            >>> api.domains_available('apsdjcpoaskdc.com', force_dict=True)
            {'apsdjcpoaskdc.com': True}
        
        """
        if len(domains) < 1:
            raise AttributeError("domains_check expects at least one domain to be specified!")
        # extra_payload = {'DomainList': ",".join(domains)}
        # xml = self.call('namecheap.domains.check', extra_payload)
        # xpath = f'.//{{{NAMESPACE}}}CommandResponse/{{{NAMESPACE}}}DomainCheckResult'
        # results = {}
        # for check_result in xml.findall(xpath):
        #     results[check_result.attrib['Domain']] = check_result.attrib['Available'] == 'true'
        results = {k: d.available for k, d in self.domains_check(*domains, force_dict=True, **user_payload).items()}
        return results if force_dict or len(domains) > 1 else results[domains[0]]
    
    domain_available = domains_available

    # https://www.namecheap.com/support/api/methods/domains/check.aspx
    @r_cache(lambda self, *args, **kwargs: _cstr(self, 'check', *args, **kwargs), 15)
    def domains_check(self, *domains, force_dict=False, **user_payload) -> Union[bool, Dict[str, DomainCheck]]:
        """Checks the availability of domains.

        For example::

            >>> api = Api('user', 'key', '12.34.56.78')
            >>> api.domains_check('taken.com', 'apsdjcpoaskdc.com')
            {
                'taken.com' : False,
                'apsdjcpoaskdc.com' : True
            }

        .. NOTE:: When checking a singular domain, a simple :class:`.bool` will be returned,
                  unless you pass ``force_dict=True`` to guarantee a :class:`.dict`

        Single domain example::

            >>> api.domains_check('taken.com')
            False
            >>> api.domains_check('apsdjcpoaskdc.com')
            True
            >>> api.domains_check('apsdjcpoaskdc.com', force_dict=True)
            {'apsdjcpoaskdc.com': True}

        """
        if len(domains) < 1:
            raise AttributeError("domains_check expects at least one domain to be specified!")
        extra_payload = {'DomainList': ",".join(domains)}
        xml = self.call('namecheap.domains.check', {**extra_payload, **user_payload})
        xpath = f'.//{{{NAMESPACE}}}CommandResponse/{{{NAMESPACE}}}DomainCheckResult'
        results = {}
        for check_result in xml.findall(xpath):
            results[check_result.attrib['Domain']] = DomainCheck.from_dict(dict(check_result.items()))
        return results if force_dict or len(domains) > 1 else results[domains[0]]
    
    @classmethod
    def _tag_without_namespace(cls, element):
        return element.tag.replace(f"{{{NAMESPACE}}}", "")

    @classmethod
    def _list_of_dictionaries_to_numbered_payload(cls, objs: Union[List[dict], List[CamelSnakeDictable]]):
        """
        [
            {'foo' : 'bar', 'cat' : 'purr'},
            {'foo' : 'buz'},
            {'cat' : 'meow'}
        ]

        becomes

        {
            'foo1' : 'bar',
            'cat1' : 'purr',
            'foo2' : 'buz',
            'cat3' : 'meow'
        }
        """
        if len(objs) > 0 and isinstance(objs[0], CamelSnakeDictable):
            objs: List[CamelSnakeDictable]
            objs: List[dict] = [cls._elements_names_fix(x) for x in objs]
        return dict(sum([
            [(k + str(i + 1), v) for k, v in d.items()] for i, d in enumerate(objs)
        ], []))

    @classmethod
    def _elements_names_fix(cls, host_record: Union[dict, CamelSnakeDictable]):
        """This method converts received message to correct send format.

        API answers you with this format:

        {
            'Name' : '@',
            'Type' : 'URL',
            'Address' : 'http://news.ycombinator.com',
            'MXPref' : '10',
            'TTL' : '100'
        }

        And you should convert it to this one in order to sync the records:

        {
            'HostName' : '@',
            'RecordType' : 'URL',
            'Address' : 'http://news.ycombinator.com',
            'MXPref' : '10',
            'TTL' : '100'
        }
        """
        if isinstance(host_record, CamelSnakeDictable):
            host_record: dict = host_record.to_dict(camel=True)

        conversion_map = [
            ("Name", "HostName"),
            ("Type", "RecordType")
        ]

        for fd in conversion_map:
            # if source field exists
            if fd[0] in host_record:
                # convert it to target field and delete old one
                host_record[fd[1]] = host_record[fd[0]]
                del(host_record[fd[0]])

        return host_record

    # https://www.namecheap.com/support/api/methods/domains/get-contacts.aspx
    @r_cache(lambda self, DomainName, **user_payload: _cstr(self, 'getContacts', DomainName, **user_payload), 60)
    def domains_getContacts(self, DomainName, **user_payload):
        """Gets contact information for the requested domain.
        There are many categories of contact info, such as admin and billing.

        The returned data is like:
        {
            'Admin' : {'FirstName' : 'John', 'LastName' : 'Connor', ...},
            'Registrant' : {'FirstName' : 'Namecheap.com', 'PhoneExt' : None, ...},
            ...
        }
        """
        xml = self.call('namecheap.domains.getContacts', {'DomainName': DomainName, **user_payload})
        xpath = f'.//{{{NAMESPACE}}}CommandResponse/{{{NAMESPACE}}}DomainContactsResult/*'
        results = {}
        for contact_type in xml.findall(xpath):
            fields_for_one_contact_type = {}
            for contact_detail in contact_type.findall('*'):
                fields_for_one_contact_type[self._tag_without_namespace(contact_detail)] = contact_detail.text
            results[self._tag_without_namespace(contact_type)] = fields_for_one_contact_type
        return results
    
    get_contacts = domains_getContacts
    
    # https://www.namecheap.com/support/api/methods/domains-dns/set-hosts.aspx
    def domains_dns_setHosts(self, domain: str, *host_records: Union[dict, DomainRecord]) -> dict:
        """
        Replaces / Sets the DNS host records for a domain.

        .. WARNING::    This method will COMPLETELY REPLACE the records on ``domain`` with ``host_records``.
                        If you want to ADD / APPEND a new record to a domain, you should use :meth:`.domains_dns_addHost`
                        (alias: :meth:`.add_record`)
        
        Example:

        >>> api = Api('user', 'key', '12.34.56.78')
        >>> api.domains_dns_setHosts('example.com',
        ...     dict(HostName='@', RecordType='URL', Address='http://news.ycombinator.com', MXPref='10', TTL='100'),
        ...     dict(HostName='www', RecordType='CNAME', Address='example.com', MXPref='10', TTL='100'),
        ... )
        """

        extra_payload = self._list_of_dictionaries_to_numbered_payload(list(host_records))
        sld, tld = domain.split(".")
        extra_payload.update(dict(SLD=sld, TLD=tld))
        self.clear_cache_domain(domain)
        return self.get_element_dict(self.call("namecheap.domains.dns.setHosts", extra_payload), 'DomainDNSSetHostsResult')

    replace_records = domains_dns_setHosts

    # https://www.namecheap.com/support/api/methods/domains-dns/set-custom.aspx
    def domains_dns_setCustom(self, domain: str, *nameservers: Union[str, Iterable], **extra_payload) -> dict:
        """Sets the domain to use the supplied set of nameservers.

        **Example Usage**::

            >>> api = Api('user', 'key', '12.34.56.78')
            >>> # (Recommended) Pass each nameserver you want to set, as positional arguments
            >>> api.domains_dns_setCustom('example.com', 'ns1.example.com', 'ns2.example.com')
            >>> # (Alternative) Pass the nameservers as a single list argument
            >>> api.domains_dns_setCustom('example.com', ['ns1.example.com', 'ns2.example.com'])
            >>> # (Alternative) Pass the nameservers as a single string argument, separated by commas
            >>> api.domains_dns_setCustom('example.com', 'ns1.example.com,ns2.example.com')
            >>> # (Alternative) Pass the nameservers directly into the payload with the kwarg `Nameservers`, separated by commas
            >>> api.domains_dns_setCustom('example.com', Nameservers='ns1.example.com,ns2.example.com')
        
        """
        payload = {'SLD': (domain.split("."))[0], 'TLD': (domain.split("."))[1]}
        nameservers = list(nameservers)
        if len(nameservers) == 1:
            if isinstance(nameservers[0], dict):
                # noinspection PyTypeChecker
                payload['Nameservers'] = nameservers[0]['Nameservers']
            elif isinstance(nameservers[0], (list, set, tuple)):
                payload['Nameservers'] = ','.join(nameservers[0])
            else:
                payload['Nameservers'] = nameservers[0]
        elif len(nameservers) == 0:
            if 'Nameservers' not in extra_payload:
                raise AttributeError("domains_dns_setCustom expects at least one nameserver to be specified!")
        else:
            payload['Nameservers'] = ','.join(nameservers)

        self.clear_cache_domain(domain)
        return self.get_element_dict(
            self.call("namecheap.domains.dns.setCustom", {**payload, **extra_payload}),
            'DomainDNSSetCustomResult'
        )
    
    set_nameservers = domains_dns_setCustom
    
    # https://www.namecheap.com/support/api/methods/domains-dns/get-hosts.aspx
    def _domains_dns_getHosts(self, domain: str, **user_payload) -> List[dict]:
        """Retrieves DNS host record settings. Note that the key names are different from those
        you use when setting the host records."""
        sld, tld = domain.split(".")
        extra_payload = dict(SLD=sld, TLD=tld)
        xml = self.call("namecheap.domains.dns.getHosts", {**extra_payload, **user_payload})
        xpath = './/{%(ns)s}CommandResponse/{%(ns)s}DomainDNSGetHostsResult/*' % {'ns': NAMESPACE}
        results = []
        for host in xml.findall(xpath):
            results.append(host.attrib)
        return results

    @r_cache(lambda self, domain, **user_payload: _cstr(self, 'dns_getHosts', domain, **user_payload), 20)
    def domains_dns_getHosts(self, domain: str, **user_payload) -> List[DomainRecord]:
        return list(DomainRecord.from_list(
            self._domains_dns_getHosts(domain, **user_payload)
        ))

    list_records = domains_dns_getHosts

    def domains_dns_addHost_obj(self, domain: str, host_record: Union[dict, DomainRecord]) -> dict:
        """
        This method is absent in original API. The main idea is to let user add one record
        while having zero knowledge about the others. Method gonna get full records list, add
        single record and push it to the API.

        Example:

        api.domains_dns_addHost('example.com', {
            "RecordType": "A",
            "HostName": "test",
            "Address": "127.0.0.1",
            "MXPref": 10,
            "TTL": 1800
        })
        """
        host_records_remote = self.domains_dns_getHosts(domain)

        log.debug("Remote: %i" % len(host_records_remote))

        host_records_remote.append(host_record)
        host_records_remote = [self._elements_names_fix(x) for x in host_records_remote]

        log.debug("To set: %i" % len(host_records_remote))

        extra_payload = self._list_of_dictionaries_to_numbered_payload(host_records_remote)
        sld, tld = domain.split(".")
        extra_payload.update(dict(SLD=sld, TLD=tld))
        self.clear_cache_domain(domain)
        return self.get_element_dict(self.call("namecheap.domains.dns.setHosts", extra_payload), 'DomainDNSSetHostsResult')

    add_record_obj = domains_dns_addHost_obj

    # https://www.namecheap.com/support/api/methods/domains-dns/get-list.aspx
    @r_cache(lambda self, domain, **user_payload: _cstr(self, 'dns_getList', domain, **user_payload), 20)
    def domains_dns_getList(self, domain: str, **user_payload) -> List[str]:
        """
        Retrieves the current nameservers for ``domain``

        Aliases: :meth:`.get_nameservers` and :meth:`.list_nameservers`

        **Example Usage**::

            >>> api = Api('user', 'key', '12.34.56.78')
            >>> api.domains_dns_getList('example.com')
            ['dns1.registrar-servers.com', 'dns2.registrar-servers.com']
            >>> api.get_nameservers('privex.cc')
            ['ns1.privex.io', 'ns2.privex.io', 'ns3.privex.io']
        
        """
        sld, tld = domain.split(".")
        extra_payload = dict(SLD=sld, TLD=tld)
        xml = self.call("namecheap.domains.dns.getList", {**extra_payload, **user_payload})
        xpath = f'.//{{{NAMESPACE}}}CommandResponse/{{{NAMESPACE}}}DomainDNSGetListResult/*'
        return [host.text for host in xml.findall(xpath)]
    
    get_nameservers = domains_dns_getList
    list_nameservers = domains_dns_getList

    def domains_dns_addHosts(self, domain: str, *records: DomainRecord) -> dict:
        """
        Add multiple records ( as :class:`.DomainRecord` objects ) to a domain, passed as positional arguments.
        
        Aliases: :meth:`.add_records`
        
        **Example Usage**::
        
            >>> api = Api('user', 'key', '12.34.56.78')
            >>> api.add_records(
            ...     'example.org',
            ...     DomainRecord('A', '1.2.3.4', 'www'),
            ...     DomainRecord('AAAA', '2a07:e00::1234', 'www'),
            ...     DomainRecord('A', '1.2.3.4'),
            ...     DomainRecord('AAAA', '2a07:e00::1234'),
            ...)
        
        :param domain:
        :param records:
        :return:
        """
        curr_records = list(self.domains_dns_getHosts(domain))
        log.debug("Existing records: %s", curr_records)
        return self.domains_dns_setHosts(domain, *curr_records, *records)

    add_records = domains_dns_addHosts

    def domains_dns_addHost(
            self, domain: str, record_type: str, value: str, hostname: str = "@", ttl: Union[int, str] = 300, **rec_data
    ) -> dict:
        """
        This method is absent in Namecheap's official HTTP API.
        
        Alias: :meth:`.add_record`
        
        We emulate adding a singular record by first obtaining the current records with :meth:`.domains_dns_getHosts`,
        then adding the record you've passed to this method to the current records list in the appropriate format.
        
        Then we call the API method ``namecheap.domains.dns.setHosts`` to completely overwrite the domain's records
        with this new list of records - containing the previous records, and the new record you've added.
        
        NOTE: If you need to add multiple records at once, use :meth:`.domains_dns_addHosts` ( alias :meth:`.add_records` )
        
        
        **Example**::

            >>> api = Api('user', 'key', '12.34.56.78')
            >>> # Add an 'A' record with the value '127.0.0.1' on 'test.example.com'
            >>> api.domains_dns_addHost('example.com', 'A', '127.0.0.1', 'test')
            >>> # Add a 'TXT' record to the root domain 'example.com' containing 'hello world'
            >>> api.domains_dns_addHost('example.com', 'TXT', 'hello world')
            >>> # Add some mail server records (Gmail used as an example) to example.org (using default hostname ``@``)
            >>> api.add_record('example.org', 'MX', 'aspmx.l.google.com.', mx_pref=1)
            >>> api.add_record('example.org', 'MX', 'alt1.aspmx.l.google.com.', mx_pref=5)
            >>> api.add_record('example.org', 'MX', 'alt2.aspmx.l.google.com.', mx_pref=5)
        
        
        You may alternatively use :meth:`.domains_dns_addHost_obj` (alias :meth:`.add_record_obj`) if you'd like to specify
        
        
        :param str domain: The domain on your Namecheap domain to add a record to
        :param str record_type: The record type to add, e.g. ``A``, ``AAAA``, ``CNAME``, ``TXT``, etc.
        :param str value: The value / contents of the record, e.g. ``127.0.0.1`` for an ``A`` record,
                          or ``2a07:e00::1`` for an ``AAAA`` record.
        :param str hostname: The "zone" / "sub-domain" to add the record to. Defaults to ``@`` which means the root domain.
        :param int|str ttl: TTL means "time to live", a technical term which just means "how many seconds should DNS
                            servers cache this record for". It defaults to ``300`` seconds (5 minutes).
        
        :keyword int|str mx_pref: Mail server preference - this parameter only matters if you're adding an ``MX`` record.
                                  It defaults to ``10``
        """
        rec_data = {**rec_data, **dict(type=record_type.upper(), address=value, name=hostname, ttl=ttl)}
        dr = DomainRecord.from_dict(rec_data)
        
        return self.domains_dns_addHost_obj(domain, dr)

    def clear_cache_domain(self, domain: str, domain_list=True, info=True, nameservers=True, records=True, check=True):
        if domain_list: self.clear_cache_key('getList', ListType=None, SearchTerm=None, PageSize=None, SortBy=None)
        if info: self.clear_cache_key('getInfo', domain, None)
        if nameservers: self.clear_cache_key('dns_getHosts', domain)
        if records: self.clear_cache_key('dns_getList', domain)
        if check: self.clear_cache_key('check', domain)

    def clear_cache_key(self, func: str, *args, **kwargs) -> bool:
        key = _cstr(self, func, *args, **kwargs)
        return cached.remove(key)

    add_record = domains_dns_addHost

    def domains_dns_delHost(self, domain, record_type: str, value: str, hostname="@") -> Union[dict, bool]:
        """
        This method is absent in original API as well. It executes non-atomic remove operation over the host record which has the
        following Type, Hostname and Address.

        **Example**::
        
            >>> api = Api('user', 'key', '12.34.56.78')
            >>> # Delete the 'A' record for 'test.example.com' which contains '127.0.0.1'
            >>> api.domains_dns_delHost('example.com', "A", "127.0.0.1", "test")
            >>> # Delete the 'TXT' record for 'example.com' which contains 'some verification code'
            >>> api.domains_dns_delHost('example.com', record_type='TXT', value='some verification code')
        
        """
        host_records_remote = self.domains_dns_getHosts(domain, r_cache=False)

        log.debug("Remote: %i" % len(host_records_remote))

        host_records_new = []
        for r in host_records_remote:
            if all([r.type == record_type, r.name == hostname, r.address == value]):
                # skipping this record as it is the one we want to delete
                pass
            else:
                host_records_new.append(r)

        host_records_new = [self._elements_names_fix(x) for x in host_records_new]

        log.debug("To set: %i" % len(host_records_new))

        # Check that we delete not more than 1 record at a time
        if len(host_records_remote) != len(host_records_new) + 1:
            sys.stderr.write(
                f"Something went wrong while removing host record, delta > 1: "
                f"{len(host_records_remote):d} -> {len(host_records_new):d}, aborting API call.\n"
            )
            return False

        extra_payload = self._list_of_dictionaries_to_numbered_payload(host_records_new)
        sld, tld = domain.split(".")
        extra_payload.update(dict(SLD=sld, TLD=tld))
        res = self.get_element_dict(self.call("namecheap.domains.dns.setHosts", extra_payload), 'DomainDNSSetHostsResult')
        self.clear_cache_key('getList', ListType=None, SearchTerm=None, PageSize=None, SortBy=None)
        self.clear_cache_key('getInfo', domain, None)
        self.clear_cache_key('dns_getHosts', domain)
        self.clear_cache_key('dns_getList', domain)
        return res

    delete_record = domains_dns_delHost
    remove_record = domains_dns_delHost

    # https://www.namecheap.com/support/api/methods/domains/get-list/
    # @r_cache(lambda self, *args, **kwargs: _cstr(self, 'getList', *args, **kwargs), 60)
    def domains_getList(self, ListType=None, SearchTerm=None, PageSize=None, SortBy=None, **user_payload) -> Generator[Domain, None, None]:
        """
        Retrieve a list of all domains on your Namecheap account - as a :class:`.Generator` / iterable of :class:`.Domain`
        
        Alias: :meth:`.list_domains`
        
        Each object represents one domain name the user has registered, for example
        
            >>> api = Api('user', 'key', '12.34.56.78')
            >>> # Since a generator is returned, we use list() to iterate over the generator and turn it into a simple list,
            >>> # which allows us to select domains by list index
            >>> doms = list(api.domains_getList())
            >>> print(doms)
            [
                 Domain(id='615175', name='20200901-123648-4052412677995005.com', user='PrivexExample',
                        created=datetime.datetime(2020, 9, 1, 0, 0), expires=datetime.datetime(2021, 9, 1, 0, 0) is_expired=False,
                        is_locked=False, auto_renew=False, whois_guard='NOTPRESENT', is_premium=False, is_our_dns=True),
                 Domain(id='615176', name='20200901-123702-2388735430231697.com', user='PrivexExample',
                        created=datetime.datetime(2020, 9, 1, 0, 0), expires=datetime.datetime(2021, 9, 1, 0, 0), is_expired=False,
                        is_locked=False, auto_renew=False, whois_guard='NOTPRESENT', is_premium=False, is_our_dns=True),
                 Domain(id='615177', name='20200901-123737-1620188403732420.com', user='PrivexExample',
                        created=datetime.datetime(2020, 9, 1, 0, 0), expires=datetime.datetime(2021, 9, 1, 0, 0) is_expired=False,
                        is_locked=False, auto_renew=False, whois_guard='NOTPRESENT', is_premium=False, is_our_dns=True),
                 Domain(id='615025', name='pvxtest.org', user='PrivexExample', created=datetime.datetime(2020, 9, 1, 0, 0),
                        expires=datetime.datetime(2021, 9, 1, 0, 0) is_expired=False, is_locked=False, auto_renew=False,
                        whois_guard='ENABLED', is_premium=False, is_our_dns=True),
                 Domain(id='615026', name='pvxtest2.org', user='PrivexExample', created=datetime.datetime(2020, 9, 1, 0, 0),
                        expires=datetime.datetime(2021, 9, 1, 0, 0) is_expired=False, is_locked=False, auto_renew=False,
                        whois_guard='ENABLED', is_premium=False, is_our_dns=True)
            ]
            >>> d = doms[3]
            >>> print(d.name)
            'pvxtest.org'
            >>> print(d.created)
            2020-09-01 00:00:00
            >>> # You can access keys via both attribute (.created) and key/dict style (['created'])
            >>> print(d['created'])
            2020-09-01 00:00:00
            >>> # If you need the original domain data - as received from Namecheap, without any type conversions,
            >>> # then you can access .raw_data - which holds the original dict data before it was parsed/casted/converted
            >>> # into native Python types.
            >>> print(d.raw_data)
            {
                'ID': '615025', 'Name': 'pvxtest.org', 'User': 'privexrslsandbox',
                'Created': '09/01/2020', 'Expires': '09/01/2021', 'IsExpired': 'false',
                'IsLocked': 'false', 'AutoRenew': 'false', 'WhoisGuard': 'ENABLED',
                'IsPremium': 'false', 'IsOurDNS': 'true'
            }
        """

        use_cache = user_payload.pop('r_cache', user_payload.pop('use_cache', True))
        # The payload is a dict of GET args that is passed to
        # the lazy-loading iterator so that it can know how to
        # get more results.
        extra_payload = {'Page': 1}
        if ListType:
            extra_payload['ListType'] = ListType
        if SearchTerm:
            extra_payload['SearchTerm'] = SearchTerm
        if PageSize:
            extra_payload['PageSize'] = PageSize
        if SortBy:
            extra_payload['SortBy'] = SortBy
        extra_payload = {**extra_payload, **user_payload}
        payload, extra_payload = self._payload('namecheap.domains.getList', extra_payload)
        cache_key = _cstr(self, 'getList', ListType=ListType, SearchTerm=SearchTerm, PageSize=PageSize, SortBy=SortBy)
        yield from self.LazyGetListIterator(
            self, payload, dtclass=Domain, cache_key=cache_key, use_cache=use_cache
        )
    
    list_domains = domains_getList

    # https://www.namecheap.com/support/api/methods/domains/renew/
    def domains_renew(
            self, domain: str, years: int = 1, promo_code: str = None, is_premium: bool = None,
            premium_price: str = None, **user_payload
    ) -> dict:
        """
        This method is absent in original API. The main idea is to let user add one record
        while having zero knowledge about the others. Method gonna get full records list, add
        single record and push it to the API.

        Example:

        api.domains_dns_addHost('example.com', {
            "RecordType": "A",
            "HostName": "test",
            "Address": "127.0.0.1",
            "MXPref": 10,
            "TTL": 1800
        })
        """
        payload = {
            'DomainName': domain,
            'Years': str(int(years) if not isinstance(years, int) else years)
        }
        if not empty(promo_code): payload['PromotionCode'] = promo_code
        if not empty(is_premium): payload['IsPremiumDomain'] = api_string(is_premium)
        if not empty(premium_price): payload['PremiumPrice'] = api_string(premium_price)
        
        payload = {**payload, **user_payload}
        
        res = self.call("namecheap.domains.renew", payload)
        renew_result = self.get_element_dict(res, 'DomainRenewResult')
        renew_result['ExpiredDate'] = self.get_element(res, 'ExpiredDate').text.strip()
        renew_result['NumYears'] = self.get_element(res, 'NumYears').text.strip()
        self.clear_cache_domain(domain, nameservers=False, records=False)
        return renew_result
    
    renew_domain = domains_renew

    # https://www.namecheap.com/support/api/methods/domains/get-info/
    @r_cache(
        lambda self, domain, hostname=None, **user_payload: _cstr(self, 'getInfo', domain, hostname, **user_payload),
        60
    )
    def domains_getInfo(self, domain: str, hostname: str = None, **user_payload) -> DomainDetails:
        """
        
        Example::
        
            >>> info = self.domains_getInfo('pvxtest.org')
            >>> print(info)
            DomainDetails(
                status='Ok', id=615025, domain_name='pvxtest.org',
                owner_name='privexrslsandbox', is_owner=True, is_premium=False,
                domain_details={
                    'CreatedDate': '09/01/2020', 'ExpiredDate': '09/01/2023', 'NumYears': '0'
                },
                lock_details={},
                whoisguard={
                    'Enabled': 'True',
                    'ID': '502832', 'ExpiredDate': '09/01/2021', '
                    EmailDetails': {
                        'WhoisGuardEmail': 'a928cedbc88e44a9907ad0af8630fe20.protect@whoisguard.com',
                        'ForwardedTo': 'company@privex.io',
                        'LastAutoEmailChangeDate': '09/01/2020', 'AutoEmailChangeFrequencyDays': '3'
                    }
                },
                premium_dns_subscription={
                    'UseAutoRenew': 'false', 'SubscriptionId': '-1',
                    'CreatedDate': '0001-01-01T00:00:00', 'ExpirationDate': '0001-01-01T00:00:00',
                    'IsActive': 'false'
                },
                dns_details={
                    'ProviderType': 'CUSTOM', 'IsUsingOurDNS': 'false',
                    'HostCount': '4', 'EmailType': 'FWD',
                    'DynamicDNSStatus': 'false', 'IsFailover': 'false',
                    'Nameservers': ['ns1.privex.io', 'ns2.privex.io', 'ns3.privex.io']
                },
                nameservers=['ns1.privex.io', 'ns2.privex.io', 'ns3.privex.io'],
                modification_rights={'All': 'true'}
            )
            >>> print(info.created_date)
            2020-09-01 00:00:00
            >>> print(info.expired_date)
            2023-09-01 00:00:00
            >>> info.days_until_expires
            1094
            >>> info.has_whoisguard
            True
            >>> info.has_premium_dns
            False
            >>> print(info.nameservers)
            ['ns1.privex.io', 'ns2.privex.io', 'ns3.privex.io']
            
        """
        payload = {
            'DomainName': domain,
        }
        if not empty(hostname): payload['HostName'] = hostname
    
        payload = {**payload, **user_payload}
    
        res = self.call("namecheap.domains.getInfo", payload)
        info_result = self.get_element_dict(res, 'DomainGetInfoResult')
        domdet = info_result['DomainDetails'] = self.get_element_content_dict(res, 'DomainDetails')
        if 'CreatedDate' in domdet: info_result['CreatedDate'] = domdet['CreatedDate']
        if 'ExpiredDate' in domdet: info_result['ExpiredDate'] = domdet['ExpiredDate']
        if 'NumYears' in domdet: info_result['NumYears'] = domdet['NumYears']
        info_result['ExpiredDate'] = self.get_element_text(res, 'ExpiredDate')
        
        info_result['Whoisguard'] = {**self.get_element_dict(res, 'Whoisguard'), **self.get_element_content_dict(res, 'Whoisguard')}
        info_result['Whoisguard']['EmailDetails'] = self.get_element_dict(res, 'EmailDetails')
        info_result['DnsDetails'] = self.get_element_dict(res, 'DnsDetails')
        info_result['Nameservers'] = info_result['DnsDetails']['Nameservers'] = [n.text for n in self.get_element(res, 'DnsDetails')]
        info_result['ModificationRights'] = info_result['Modificationrights'] = self.get_element_dict(res, 'Modificationrights')
        info_result['PremiumDnsSubscription'] = self.get_element_content_dict(res, 'PremiumDnsSubscription')
        info_result['LockDetails'] = self.get_element_dict(res, 'LockDetails')
        
        return DomainDetails.from_dict(info_result)
    
    get_domain_info = domains_getInfo
