import copy
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from export_kml import NS, export, registration


def sample():
    return {'name':'Synthetic boundary','confidence':'medium','boundary_role':'study_boundary',
            'boundary_complete':True,'source':{'pdf':'synthetic.pdf','pdf_page':1,'figure':'synthetic only'},
            'datum_note':'Synthetic WGS84 test coordinates','boundary_evidence':'Synthetic square',
            'boundary_pixels':[[0,0],[10,0],[10,10],[0,10]],
            'registration':{'method':'axis_ticks','north_up_confirmed':True,
                            'x_ticks':[[0,105],[10,105.01]],'y_ticks':[[0,1.01],[10,1]]}}


class ExportTests(unittest.TestCase):
    def export(self,c,**kwargs):
        with tempfile.TemporaryDirectory() as folder:
            r=export(c,None,folder,**kwargs)
            root=ET.parse(Path(folder)/'study_area_WGS84_EPSG4326.kml')
            for el in root.findall('.//{'+NS+'}coordinates'):
                triples=[list(map(float,t.split(','))) for t in el.text.split()]
                self.assertEqual(triples[0],triples[-1])
                self.assertTrue(all(len(t)==3 and -180<=t[0]<=180 and -90<=t[1]<=90 and t[2]==0 for t in triples))
            return r

    def test_square_kml_and_geodesic_area(self):
        r=self.export(sample())
        self.assertTrue(1.22<r['geometry']['geodesic_area_km2']<1.24)

    def test_multipart_hole_subtracts_area(self):
        c=sample();c['polygons']=[{'name':'outer','boundary_pixels':c['boundary_pixels'],'holes_pixels':[[[2,2],[8,2],[8,8],[2,8]]]},
                                 {'name':'island','boundary_pixels':[[12,0],[14,0],[14,2],[12,2]]}]
        r=self.export(c)
        self.assertEqual((r['geometry']['polygon_count'],r['geometry']['hole_count']),(2,1))
        self.assertTrue(0.82<r['geometry']['geodesic_area_km2']<0.85)

    def test_bowtie_is_rejected(self):
        c=sample();c['boundary_pixels']=[[0,0],[10,10],[0,10],[10,0]]
        with self.assertRaisesRegex(ValueError,'invalid polygon'):self.export(c)

    def test_projected_ticks_are_converted(self):
        c=sample();c['registration'].update(method='projected_ticks',map_crs='EPSG:32648',x_ticks=[[0,500000],[10,501000]],y_ticks=[[0,1000],[10,0]])
        r=self.export(c);w,s,e,n=r['geometry']['bounds_lonlat']
        self.assertAlmostEqual(w,105,places=6);self.assertAlmostEqual(s,0,places=6)
        self.assertTrue(105.008<e<105.010 and .008<n<.010)

    def test_collinear_gcps_are_rejected(self):
        c=sample();c['registration']={'method':'affine_gcps','gcps':[{'pixel':[i,i],'lonlat':[105+i*.001,1+i*.001]} for i in range(3)]}
        with self.assertRaisesRegex(ValueError,'collinear'):self.export(c)

    def test_affine_rotated_and_extrapolation(self):
        c=sample();px=[[0,0],[10,0],[0,10],[10,10]]
        c['registration']={'method':'affine_gcps','gcps':[{'pixel':[x,y],'lonlat':[105+(x+y)*.001,1+(x-y)*.001]} for x,y in px]}
        c['boundary_pixels']=[[0,0],[20,0],[20,20],[0,20]]
        r=self.export(c)
        self.assertGreater(r['registration']['vertices_outside_gcp_hull'],0)
        self.assertAlmostEqual(r['geometry']['bounds_lonlat'][2],105.04,places=6)
        self.assertEqual(r['registration']['leave_one_out_count'],4)

    def test_proxy_cannot_masquerade_as_boundary(self):
        c=sample();c['registration']={'method':'text_bbox_proxy','bounds_lonlat':[105,1,106,2]}
        with self.assertRaisesRegex(ValueError,'allow-bbox-proxy'):self.export(c)
        c.update(name='BBOX_PROXY_NOT_BOUNDARY',confidence='low',boundary_role='bbox_proxy')
        self.assertTrue(self.export(c,allow_bbox_proxy=True)['geometry']['valid'])

    def test_bbox_fit_needs_extrema_evidence(self):
        c=sample();c['registration']={'method':'outline_bbox_fit','bounds_lonlat':[105,1,106,2]}
        with self.assertRaisesRegex(ValueError,'extrema'):self.export(c)
        c['registration']['extrema_evidence']='Synthetic exact extrema';c['confidence']='low'
        self.assertTrue(self.export(c)['geometry']['valid'])

    def test_dimension_mismatch_and_incomplete_boundary(self):
        c=sample();c['boundary_complete']=False
        with self.assertRaisesRegex(ValueError,'incomplete'):self.export(c)
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'map.png';Image.new('RGB',(20,20)).save(f)
            with self.assertRaisesRegex(ValueError,'dimensions'):export(sample(),f,Path(folder)/'out')

    def test_no_north_up_or_degree_metre_confusion(self):
        c=sample();c['registration']['north_up_confirmed']=False
        with self.assertRaisesRegex(ValueError,'north_up'):self.export(c)
        c=sample();c['registration']['x_ticks']=[[0,500000],[10,501000]]
        with self.assertRaisesRegex(ValueError,'longitude/latitude'):self.export(c)

    def test_map_frame_fallback_uses_whole_rectangle(self):
        from PIL import Image
        c=sample();c.pop('boundary_pixels')
        c.update(name='Synthetic MAP_FRAME_EXTENT',confidence='low',boundary_role='map_frame_extent',map_frame_pixels=[1,1,9,9],image_size=[12,12])
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'map.png';Image.new('RGB',(12,12)).save(f)
            r=export(c,f,Path(folder)/'out')
            root=ET.parse(Path(folder)/'out'/'study_area_WGS84_EPSG4326.kml')
            data={el.get('name'):el.find('{'+NS+'}value').text for el in root.findall('.//{'+NS+'}Data')}
            self.assertEqual(data['boundary_role'],'map_frame_extent')
            self.assertEqual(data['confidence'],'low')
        self.assertEqual(r['geometry']['vertex_count'],4)
        self.assertEqual(r['registration']['extent_basis'],'georeferenced_map_frame')
        for actual,expected in zip(r['geometry']['bounds_lonlat'],[105.001,1.001,105.009,1.009]):
            self.assertAlmostEqual(actual,expected,places=7)
        self.assertTrue(any('MAP_FRAME_EXTENT' in w for w in r['warnings']))

    def test_map_frame_needs_image_and_valid_frame(self):
        from PIL import Image
        c=sample();c.pop('boundary_pixels');c.update(name='Synthetic MAP_FRAME_EXTENT',confidence='low',boundary_role='map_frame_extent',image_size=[12,12])
        with self.assertRaisesRegex(ValueError,'source map image'):self.export(c)
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'map.png';Image.new('RGB',(12,12)).save(f)
            for frame in ([9,1,1,9],[1,1,30,30]):
                c['map_frame_pixels']=frame
                with self.assertRaises(ValueError):export(c,f,Path(folder)/'out')

    def test_map_frame_cannot_claim_boundary_or_use_text_extrema(self):
        from PIL import Image
        c=sample();c.pop('boundary_pixels')
        c.update(name='Synthetic MAP_FRAME_EXTENT',confidence='low',boundary_role='map_frame_extent',map_frame_pixels=[1,1,9,9],image_size=[12,12])
        with tempfile.TemporaryDirectory() as folder:
            f=Path(folder)/'map.png';Image.new('RGB',(12,12)).save(f)
            for change in ({'confidence':'high'}, {'name':'Confirmed study boundary'},
                           {'registration':{'method':'outline_bbox_fit','bounds_lonlat':[105,1,106,2],'extrema_evidence':'text only'}}):
                invalid=copy.deepcopy(c);invalid.update(change)
                with self.assertRaises(ValueError):export(invalid,f,Path(folder)/'out')


if __name__=='__main__':unittest.main()
