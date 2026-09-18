"""Small OpenDRIVE fixtures assembled explicitly from source links."""

def lane(lid=-1,width=3.5,extra='',pre=None,post=None):
    links=''.join(f'<{tag} id="{value}"/>' for tag,value in [('predecessor',pre),('successor',post)] if value is not None)
    return f'<lane id="{lid}" type="driving"><link>{links}</link><width sOffset="0" a="{width}" b="0" c="0" d="0"/><roadMark sOffset="0" type="broken" laneChange="both"/>{extra}</lane>'


def road(rid='1',length=12,x=0,y=0,z=0,heading=0,shape='<line/>',lanes=None,link='',junction='-1',rule='RHT',elevation='',bank='',extra=''):
    if lanes is None: lanes=lane()
    side='left' if 'id="1"' in lanes and 'id="-1"' not in lanes else 'right'
    return f'''<road id="{rid}" length="{length}" junction="{junction}" rule="{rule}"><link>{link}</link>
    <type s="0" type="town"><speed max="36" unit="km/h"/></type>
    <planView><geometry s="0" x="{x}" y="{y}" hdg="{heading}" length="{length}">{shape}</geometry></planView>
    <elevationProfile><elevation s="0" a="{z}" b="0" c="0" d="0"/>{elevation}</elevationProfile>
    <lateralProfile>{bank}</lateralProfile><lanes><laneSection s="0"><center><lane id="0" type="none"><roadMark sOffset="0" type="solid" laneChange="none"/></lane></center><{side}>{lanes}</{side}></laneSection></lanes>{extra}</road>'''


def document(*roads,extra=''): return '<OpenDRIVE><header revMajor="1" revMinor="4"/>'+''.join(roads)+extra+'</OpenDRIVE>'


def connected():
    return document(road('1',lanes=lane(post=-1),link='<successor elementType="road" elementId="2" contactPoint="start"/>'),
                    road('2',x=12,lanes=lane(pre=-1),link='<predecessor elementType="road" elementId="1" contactPoint="end"/>'))
