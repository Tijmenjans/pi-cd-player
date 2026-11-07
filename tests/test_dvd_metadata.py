import unittest
from dvd_metadata import select_result,normalized
class Tests(unittest.TestCase):
 def item(self,id='tt0822832',title='Marley & Me',year=2008,kind='movie'):
  return {'id':id,'l':title,'y':year,'qid':kind,'s':'Owen Wilson, Jennifer Aniston','rank':1234}
 def test_ampersand_label_and_no_rank_rating(self):
  r=select_result('MARLEY_AND_ME',[self.item()]);self.assertEqual(r['title'],'Marley & Me');self.assertEqual(r['year'],2008);self.assertNotIn('rating',r);self.assertNotIn('rank',r)
 def test_sequel_not_used(self):self.assertIsNone(select_result('MARLEY_AND_ME',[self.item(title='Marley & Me: The Puppy Years')]))
 def test_ambiguous_remake_hidden(self):self.assertIsNone(select_result('IT',[self.item(title='It',year=1990),self.item(id='tt9999999',title='It',year=2017)]))
 def test_year_disambiguates(self):self.assertEqual(select_result('IT 2017',[self.item(title='It',year=1990),self.item(id='tt9999999',title='It',year=2017)])['year'],2017)
 def test_generic_and_actor_hidden(self):
  self.assertIsNone(select_result('DVD VIDEO',[self.item(title='DVD Video')]))
  self.assertIsNone(select_result('Marley & Me',[self.item(kind='person')]))
 def test_link_is_constructed(self):self.assertEqual(select_result('Marley & Me',[self.item()])['url'],'https://www.imdb.com/title/tt0822832/')
if __name__ == '__main__': unittest.main()
