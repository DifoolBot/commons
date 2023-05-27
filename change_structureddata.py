import pywikibot
import json
from pywikibot import textlib
import os
import time
import platform
from datetime import datetime


#https://byabbe.se/2020/09/15/writing-structured-data-on-commons-with-python
#https://github.com/multichill/toollabs/blob/master/bot/commons/wikidata_uploader.py
#https://www.wikidata.org/wiki/Special:EntityData/Q12418.json   returns page as json

#commonssite = pywikibot.Site('commons', 'commons')
#commonssite.login()
#commonssite.get_tokens('csrf') # preload csrf token

statementTypes = {
  'P31': 'Item',
  'P170': 'Item', #creator
  'P195': 'Item', #collection
  'P217': 'String',
  'P528': 'String', #catalog code
  'P571': 'Point in time', #inception
  'P1071': 'Item',     # location of creation
  'P2048': 'Quantity',
  'P2049': 'Quantity'
}
class ChangeStructuredDataBot:

  def __init__(self, pagetitle, url, htmfile, statements):
       
    self.pagetitle = pagetitle
    self.url = url
    self.site = pywikibot.Site('commons', 'commons')
    self.site.login()
    self.site.get_tokens('csrf')
    self.repo = self.site.data_repository()
    self.allStatements = statements
    self.addStatements = []
    self.test = True
    self.success = False
    self.includeReference = True
    
    modification_time = os.path.getmtime(htmfile)
    local_time = time.ctime(modification_time)
    date_of_created = datetime.strptime(
        local_time, "%a %b %d %H:%M:%S %Y")  # Convert string to date format
    self.reference = self.getReference('Q190804', self.url,
                                       date_of_created.year, date_of_created.month, date_of_created.day)

  def run(self):
       
    imagefile = pywikibot.Page(self.site, self.pagetitle)
    self.media_identifier = 'M{}'.format(imagefile.pageid)

    #check cat
    text = imagefile.text
    cats = textlib.getCategoryLinks(
            text, self.site, [])
    for cat in cats:
      if cat.title() == "Category:Uncategorized images of the Rijksmuseum (Misidentified)":
        print('Skipped: misidentified: {}'.format(self.pagetitle))    
        return
      
    #check prop
    request = self.site.simple_request(action='wbgetentities', ids=self.media_identifier)
    raw = request.submit()
    existing_data = None
    if raw.get('entities').get(self.media_identifier).get('pageid'):
      existing_data = raw.get('entities').get(self.media_identifier)
    if existing_data == None:
      print('Skipped: no data, probably redirect: {}'.format(self.pagetitle))    
      return


    P6243 = existing_data.get('statements').get('P6243')
    if P6243 != None:
      print('Skipped: digital representation of: {}'.format(self.pagetitle))    
      return

    self.determineAdd(existing_data)

    if (self.addStatements == []): 
      return

    itemdata = self.getStructuredData()
    #summary = 'this newly uploaded file depicts and is a digital representation of [[d:Special:EntityPage/%s]]' % (metadata.get('item'),)
    summary = 'update structured data'
    #print(json.dumps(itemdata))

    token = self.site.tokens['csrf']
    postdata = {'action' : 'wbeditentity',
                'format' : 'json',
                'id' : self.media_identifier,
                'data' : json.dumps(itemdata),
                'token' : token,
                'summary' : summary,
                'bot' : True,
                }
    #print (json.dumps(postdata, sort_keys=True, indent=4))
    if self.test:
      self.success = True
    else:
      request = self.site.simple_request(**postdata)
      try:
        pass
        data = request.submit()
        imagefile.touch()
        self.success = True

      # except pywikibot.data.api.APIError as e:
      #   print('Got an error from the API, the following request were made:')
      #   print(request)
      #   print('Error: {}'.format(e))    
      except Exception as err:
        print('Error: {}'.format(err))    
        
  def determineAdd(self, existing_data):
    for s in self.allStatements:
      property = s['property']
      item = s.get('item')

      if existing_data == None:
        current = None
      else:
        current = existing_data.get('statements').get(property)
      if current != None:
        print(current)
      # Q80151 (hat)
      if current == None:
        canAdd = True
      elif item == None:
        canAdd = False
      elif any(statement['mainsnak']['datavalue']['value']['id'] == item for statement in current):
        canAdd = False
      else:
        canAdd = True
      if (canAdd == True):
        self.addStatements.append(s)
    

  def getStructuredData(self):
    claims = []

    for s in self.addStatements:
      property = s['property']
      datatype = s.get('datatype')
      expDatatype = statementTypes.get(property)
      if (expDatatype != None):
        if datatype == None:
          datatype == expDatatype
        elif (datatype != 'Unknown') and (datatype!=expDatatype):
          raise Exception('unexpected datatype for ' + property)

      if (datatype=='Item'):
        item = s['item']
        snak  = self.getItemSnak(property, item)
      elif (datatype=='Quantity'):
        value = s['value']
        unit = s['unit']
        snak = self.getQuantitySnak(property, value, unit)
      elif (datatype=='String'):
        text = s['text']
        snak = self.getStringSnak(property, text)
      elif (datatype=='Monolingual text'):
        text = s['text']
        language = s['language']
        snak = self.getMonolingualTextSnak(property, text, language)
      elif (datatype=='Point in time'):
        day = s['day']
        month = s['month']
        year = s['year']
        precision = s['precision']
        snak = self.getPointInTimeSnak(property, year, month, day, precision)
      elif (datatype=='Unknown'):
        snak = self.getUnknownSnak(property)
      else:
        raise Exception('unexpected datatype for ' + property)

      if (snak != None):
        qualifiers = s.get('qualifiers')
        qualifiersSnak = self.getQualifiersSnak(qualifiers)
        toclaim = {'mainsnak': snak,
                    'type': 'statement',
                    'rank': 'normal',
                    }
        if self.includeReference:
          toclaim['references'] = self.reference
        if qualifiersSnak != None:
          toclaim['qualifiers'] = qualifiersSnak

        claims.append(toclaim)
    
    if (claims == []):
      return None
    else:
      return {'claims' : claims}

  def getReference(self, item, url, year, month, day):

    item = self.getItemSnak('P248', item)
    retrieved = self.getPointInTimeSnak('P813', year, month, day, 0)
    url = self.getURLSnak('P854', url)
    obj = [{'snaks': {
              'P248': [item],
              'P813': [retrieved],
              'P854': [url]
              },
            'snaks-order': [
              'P248',
              'P854',
              'P813'
              ]}]
    return obj

  def getPointInTimeSnak(self, property, year, month, day, precision):

    # The precision is: 0 - billion years, 1 - hundred million years, ..., 6 - millennium, 7 - century, 8 - decade, 9 - year (default), 10 - month, 11 - day
    if (precision == None) or (precision == 0):
      if (day != None) and (day != 0):
        precision = 11
      elif (month != None) and (month != 0):
        precision = 10
      elif (year != None) and (year != 0):
        precision = 9
      else:
        return None
    
    if (month==None): month = 0
    if (day==None): day = 0

    #'+1863-01-01T00:00:00Z'
    timestr = '+{:04d}-{:02d}-{:02d}T00:00:00Z'.format(year, month, day)
    
    if (year>=1582):
      calendarmodel='http://www.wikidata.org/entity/Q1985727' #gregorian
    else:
      calendarmodel='http://www.wikidata.org/entity/Q1985786' #julian
    

    obj = {'snaktype': 'value',
           'property': property,
           'datavalue': {'value': {'time': timestr,
                                   'timezone': 0,
                                   'before': 0,
                                   'after': 0,
                                   'precision': precision,
                                   'calendarmodel': calendarmodel
                                   },
                         'type': 'time'
                         },
           'datatype': 'time'
           }
    return obj
  
  def getItemSnak(self, property, item):

    itemid = item.replace('Q', '')

    obj = {'snaktype': 'value',
           'property': property,
           'datavalue': {'value': {'numeric-id': itemid,
                                   'id': item,
                                   },
                         'type': 'wikibase-entityid',
                         }

           }
    return obj
  
  def getUnknownSnak(self, property):

    obj = {'snaktype': 'somevalue',
           'property': property,
           'datatype': 'wikibase-item'
           }
    return obj

  def getQuantitySnak(self, property, value, unit):
  
    entity = 'http://www.wikidata.org/entity/' + unit

    obj = {'snaktype':'value',
           'property':property,
           'datavalue':{ 'value':{ 'amount':value,
                                    'unit':entity
                                  },
                          'type':'quantity'
                      },
            'datatype':'quantity'
          }
    return obj

  def getURLSnak(self, property, url):

    obj = {'snaktype': 'value',
           'property': property,
           'datavalue': {'value': url,
                         'type': 'string'
                         },
           'datatype': 'url'
           }
    return obj

  def getStringSnak(self, property, string):

    obj = {'snaktype': 'value',
           'property': property,
           'datavalue': {'value': string,
                         'type': 'string'
                         },
           'datatype': 'string'
           }
    return obj

  def getExternalIDSnak(self, property, externalID):

    obj = {'snaktype': 'value',
           'property': property,
           'datavalue': {'value': externalID,
                         'type': 'string'
                         },
           'datatype': 'external-id'
           }
    return obj

  def getMonolingualTextSnak(self, property, text, language):

    obj = {'snaktype': 'value',
           'property': property,
           'datavalue': {'value': {'text': text,
                                   'language': language
                                   },
                         'type': 'monolingualtext'
                         },
           'datatype': 'monolingualtext'
           }
    return obj

  def getQualifiersSnak(self, qualifiers):

    if qualifiers==None:
      return None
    
    claims = {}

    for q in qualifiers:
      property = q['property']
      datatype = q['datatype']

      if (datatype=='Item'):
        item = q['item']
        snak = self.getItemSnak(property, item)
      elif (datatype=='Quantity'):
        value = q['value']
        unit = q['unit']
        snak = self.getQuantitySnak(property, value, unit)
      elif (datatype=='String'):
        text = q['text']
        snak = self.getStringSnak(property, text)
      elif (datatype=='Point in time'):
        day = q['day']
        month = q['month']
        year = q['year']
        precision = q['precision']
        snak = self.getPointInTimeSnak(property, year, month, day, precision)
      else:
        snak = None

      if (snak != None):
        #toclaim = {property:[snak]}
        c=claims.get(property)
        if c==None:
          claims[property]=[snak]
        else:  
          claims[property]=c + [snak]
    
    if (claims == []):
      return None
    else:
      return claims
          
def main(*args):

  title=u"File:Test.svg"
  f = open('D:\\data\\commons_images\\1a59cb5a157e51eb0740eea74be5aad0410b30f3\\statements.json', mode="r", encoding="utf-8")
  d = json.load(f)

  commonspage = d['commonspage']
  statements = d['statements']
  htmfile = d['htmlfile']
  url = d['url']

  # statements = [{'property': 'P31',
  #                'item': 'Q5'},
  #               {'property': 'P571',
  #                'date': [{'year': 1863}]
  #               }]


  changeStructuredDataBot = ChangeStructuredDataBot(title, url, htmfile, statements)
  changeStructuredDataBot.test = False
  changeStructuredDataBot.includeReference = False
  changeStructuredDataBot.run()

if __name__ == "__main__":
  main()