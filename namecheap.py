import requests # pip install requests
from xml.etree.ElementTree import fromstring

# http://developer.namecheap.com/docs/doku.php?id=overview:2.environments
ENDPOINTS = {
	# To use
	# 1) browse to http://www.sandbox.namecheap.com/
	# 2) create account, my account > manage profile > api access > enable API
	# 3) add your IP address to whitelist
	'sandbox' : 'https://api.sandbox.namecheap.com/xml.response', 
	'production' : 'https://api.namecheap.com/xml.response',
}
DEBUG = True
NAMESPACE = "http://api.namecheap.com/xml.response"

class ApiError(Exception):
	def __init__(self, number, text):
		Exception.__init__(self, '%s - %s' % (number, text))
	 	self.number = number
	 	self.text = text

class Api(object):
	# Follows API spec capitalization in variable names for consistency.
	def __init__(self, ApiUser, ApiKey, UserName, ClientIP, is_sandbox = True):
		self.ApiUser = ApiUser
		self.ApiKey = ApiKey
		self.UserName = UserName
		self.ClientIP = ClientIP
		self.endpoint = ENDPOINTS['sandbox' if is_sandbox else 'production']

	def _payload(self, Command, extra_payload = {}):
		"""Make dictionary for passing to requests.get"""
		payload = {
			'ApiUser' : self.ApiUser,
			'ApiKey' : self.ApiKey,
			'UserName' : self.UserName,
			'ClientIP' : self.ClientIP,
			'Command' : Command,
		}
		payload.update(extra_payload)
		return payload

	def _fetch_xml(self, payload):
		"""Make network call and return parsed XML element"""
		r = requests.post(self.endpoint, params=payload)
		if DEBUG:
			print "--- Request ---"
			print r.url
			print "--- Response ---"
			print r.text
		xml = fromstring(r.text)

		if xml.attrib['Status'] == 'ERROR':
			# Response namespace must be prepended to tag names.			
			xpath = './/{%(ns)s}Errors/{%(ns)s}Error' % {'ns' : NAMESPACE}
			error = xml.find(xpath)
			raise ApiError(error.attrib['Number'], error.text)

		return xml

	def _call(self, Command, extra_payload = {}):
		"""Call an API command"""
		payload = self._payload(Command, extra_payload)
		xml = self._fetch_xml(payload)
		return xml

	class LazyGetListIterator(object):
		"""When listing domain names, only one page is returned
		initially. The list needs to be paged through to see all.
		This iterator gets the next page when necessary."""
		def _get_more_results(self):
			xml = self.api._fetch_xml(self.payload)
			xpath = './/{%(ns)s}CommandResponse/{%(ns)s}DomainGetListResult/{%(ns)s}Domain' % {'ns' : NAMESPACE}
			domains = xml.findall(xpath)
			for domain in domains:
				self.results.append(domain.attrib)
			self.payload['Page'] += 1

		def __init__(self, api, payload):
			self.api = api
			self.payload = payload
			self.results = []
			self.i = -1

		def __iter__(self):
			return self

		def next(self):
			self.i += 1
			if self.i >= len(self.results):
				self._get_more_results()

			if self.i >= len(self.results):
				raise StopIteration
			else:
				return self.results[self.i]				

	def domains_check(self, domains):
		"""Checks the availability of domains.

		For example
		api.domains_check(['taken.com', 'apsdjcpoaskdc.com'])

		Might result in
		{
			'taken.com' : False,
			'apsdjcpoaskdc.com' : True
		}
		"""

		# For convenience, allow a single domain to be given
		if isinstance(domains, basestring):
			return self.domains_check([domains]).items()[0][1]

		extra_payload = {'DomainList' : ",".join(domains)}
		xml = self._call('namecheap.domains.check', extra_payload)
		xpath = './/{%(ns)s}CommandResponse/{%(ns)s}DomainCheckResult' % {'ns' : NAMESPACE}
		results = {}
		for check_result in xml.findall(xpath):
			results[check_result.attrib['Domain']] = check_result.attrib['Available'] == 'true'
		return results

	@classmethod
	def _tag_without_namespace(cls, element):
		return element.tag.replace("{%s}" % NAMESPACE, "")

	def domains_getContacts(self, DomainName):
		"""Gets contact information for the requested domain. 
		There are many categories of contact info, such as admin and billing.

		The returned data is like:
		{
			'Admin' : {'FirstName' : 'John', 'LastName' : 'Connor', ...},
			'Registrant' : {'FirstName' : 'Namecheap.com', 'PhoneExt' : None, ...},
			...
		}
		"""
		xml = self._call('namecheap.domains.getContacts', {'DomainName' : DomainName})
		xpath = './/{%(ns)s}CommandResponse/{%(ns)s}DomainContactsResult/*' % {'ns' : NAMESPACE}
		results = {}
		for contact_type in xml.findall(xpath):
			fields_for_one_contact_type = {}
			for contact_detail in contact_type.findall('*'):
				fields_for_one_contact_type[self._tag_without_namespace(contact_detail)] = contact_detail.text
			results[self._tag_without_namespace(contact_type)] = fields_for_one_contact_type
		return results

	def domains_getList(self, ListType = None, SearchTerm = None, PageSize = None, SortBy = None):
		"""Returns an iterable of dicts. Each dict represents one
		domain name the user has registered, for example
		{
			'Name': 'coolestfriends.com', 
			'Created': '04/11/2012', 
			'Expires': '04/11/2018', 
			'ID': '8385859', 
			'AutoRenew': 'false', 
			'IsLocked': 'false', 
			'User': 'Bemmu', 
			'IsExpired': 'false', 
			'WhoisGuard': 'NOTPRESENT'
		}
		"""

		# The payload is a dict of GET args that is passed to
		# the lazy-loading iterator so that it can know how to
		# get more results.
		extra_payload = {'Page' : 1}
		if ListType: extra_payload['ListType'] = ListType
		if SearchTerm: extra_payload['SearchTerm'] = SearchTerm
		if PageSize: extra_payload['PageSize'] = PageSize
		if SortBy: extra_payload['SortBy'] = SortBy
		payload = self._payload('namecheap.domains.getList', extra_payload)
		return self.LazyGetListIterator(self, payload)
 