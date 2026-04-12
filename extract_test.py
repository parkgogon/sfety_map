import zipfile
from xml.etree import ElementTree as ET
import pandas as pd

def parse_kmz(filename):
    data = []
    with zipfile.ZipFile(filename, 'r') as kmz:
        with kmz.open('doc.kml', 'r') as kml_file:
            tree = ET.parse(kml_file)
            root = tree.getroot()
            # NS is usually 'http://www.opengis.net/kml/2.2'
            ns = {'kml': 'http://www.opengis.net/kml/2.2'}
            for placemark in root.findall('.//kml:Placemark', ns):
                name = placemark.find('kml:name', ns)
                name = name.text if name is not None else ''
                
                desc = placemark.find('kml:description', ns)
                desc = desc.text if desc is not None else ''
                
                point = placemark.find('.//kml:Point/kml:coordinates', ns)
                if point is not None:
                    coords = point.text.strip().split(',')
                    if len(coords) >= 2:
                        lon, lat = float(coords[0]), float(coords[1])
                        data.append({'name': name, 'description': desc, 'latitude': lat, 'longitude': lon})
    return pd.DataFrame(data)

df = parse_kmz('대구경북환경본부 소관시설 위치정보.kmz')
# pd.set_option('display.max_columns', None)
print(df.head())
print(f"Total rows: {len(df)}")
