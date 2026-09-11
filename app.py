from datetime import date
import pandas as pd,streamlit as st,plotly.express as px
from auth.access import options,current
from services.data_access import partners,actuals,targets,reviews,authorized,latest_actual,latest_target,append_excel
from services.projection_service import scenarios
from services.target_service import save
from services.performance_service import compare
from services.export_service import excel,pdf
from config.settings import REVIEW_HISTORY
from utils.formatting import money
st.set_page_config(page_title='Wealthy | Partner Platform',page_icon='🎯',layout='wide')
st.markdown('''<style>.block-container{max-width:1500px;padding-top:1rem}.kpi{background:#fff;border:1px solid #e1e7ef;border-radius:12px;padding:14px}.kl{font-size:11px;color:#687386;font-weight:700;text-transform:uppercase}.kv{font-size:25px;font-weight:800;color:#132238}.section{font-size:20px;font-weight:800;color:#132238;margin:18px 0 8px}.banner{background:#eef5fb;border:1px solid #d8e5f1;border-radius:12px;padding:12px}</style>''',unsafe_allow_html=True)
st.title('WEALTHY | Partner Income Projection & Target Tracking'); st.caption('Review → Target → Projection → Commitment → Actual → Corrective Action')
with st.sidebar:
 st.header('Access'); opts=options(); st.stop() if not opts else None; email=st.selectbox('Demo user',opts); u=current(email); st.info(f"**{u['Name']}**\n\nRole: {u['Role']}\nRM: {u.get('RM','')}\nCluster: {u.get('Cluster','')}"); st.caption('Demo filtering only — production requires company-approved SSO and server-side authorization.')
p=authorized(u); a=actuals(); t=targets(); r=reviews(); tabs=st.tabs(['Partner Review','Performance','Review History','Data / Admin'])
with tabs[0]:
 st.markdown('<div class="section">1. Partner Selection</div>',unsafe_allow_html=True); q=st.text_input('Search Partner ID / Name'); x=p if not q else p[p['Partner ID'].astype(str).str.contains(q,case=False)|p['Partner Name'].astype(str).str.contains(q,case=False)]; pid=st.selectbox('Partner',x['Partner ID'].tolist(),format_func=lambda z:f"{z} — {x.loc[x['Partner ID'].eq(z),'Partner Name'].iloc[0]}"); partner=p[p['Partner ID'].eq(pid)].iloc[0].to_dict(); act=latest_actual(pid) or {}
 st.markdown('<div class="section">2. Current Business</div>',unsafe_allow_html=True); cols=st.columns(5)
 for c,(lab,val) in zip(cols,[('Sales',money(act.get('Sales'))),('SIP',money(act.get('SIP'))),('AUM',money(act.get('AUM'))),('Clients',f"{int(act.get('Clients',0)):,}"),('New Clients',f"{int(act.get('New Clients',0)):,}")]): c.markdown(f'<div class="kpi"><div class="kl">{lab}</div><div class="kv">{val}</div></div>',unsafe_allow_html=True)
 st.markdown('<div class="section">3. Income Projection Calculator</div>',unsafe_allow_html=True); st.markdown('<div class="banner"><b>IMPORTANT:</b> Calculator formulas/rates are illustrative placeholders. Replace with approved Wealthy business logic before production.</div>',unsafe_allow_html=True)
 c1,c2=st.columns([1,2.2])
 with c1:
  sc=st.number_input('Starting Clients',0,value=int(act.get('Clients',0))); sa=st.number_input('Starting AUM (₹)',0.0,value=float(act.get('AUM',0)),step=100000.0); nc=st.number_input('New Clients / Month',0.0,5.0); sp=st.number_input('SIP / Client / Month (₹)',0.0,5000.0,step=500.0); ss=st.number_input('SIP Step-up % p.a.',0.0,1.0)/100; ls=st.number_input('Annual Lumpsum (₹)',0.0,10000.0,step=5000.0); lss=st.number_input('Lumpsum Step-up % p.a.',0.0,0.0)/100; red=st.number_input('Annual Redemption %',0.0,5.0)/100; tr=st.number_input('Trail Rate % p.a.',0.0,0.7)/100; cg=st.number_input('Market CAGR % p.a.',0.0,12.0)/100
 base={'starting_clients':sc,'starting_aum':sa,'new_clients_month':nc,'sip_client_month':sp,'sip_step':ss,'annual_lumpsum':ls,'lumpsum_step':lss,'redemption':red,'trail_rate':tr,'market_cagr':cg}
 ssn=scenarios(base)
 with c2:
  v=ssn['Target']; view=v[v.Year.isin([1,3,5,10,15,20,25])].copy();
  for col in ['Total AUM','SIP Book / Mo','Trail / Yr','Total Income']: view[col]=view[col].map(money)
  st.dataframe(view,use_container_width=True,hide_index=True); st.plotly_chart(px.bar(v[v.Year.isin([1,3,5,10,15,20,25])],x='Year',y='Total Income',title='Target scenario — projected annual income'),use_container_width=True)
 st.markdown('<div class="section">4. Conservative / Target / Stretch</div>',unsafe_allow_html=True); comp=[]
 for yr in [1,3,5,10,25]:
  row={'Year':yr}
  for s in ['Conservative','Target','Stretch']:
   z=ssn[s].loc[ssn[s].Year.eq(yr)].iloc[0]; row[f'{s} Income']=money(z['Total Income']); row[f'{s} AUM']=money(z['Total AUM'])
  comp.append(row)
 st.dataframe(pd.DataFrame(comp),use_container_width=True,hide_index=True)
 st.markdown('<div class="section">5. Final Target</div>',unsafe_allow_html=True)
 with st.form('target'):
  d1,d2,d3=st.columns(3); rd=d1.date_input('Review Date',date.today()); tm=d1.date_input('Target Month',date.today().replace(day=1)); sal=d1.number_input('Sales Target (₹)',0.0,float(act.get('Sales',0)),step=100000.0); sip=d2.number_input('SIP Target (₹)',0.0,float(act.get('SIP',0)),step=10000.0); aum=d2.number_input('AUM Target (₹)',0.0,float(act.get('AUM',0)),step=100000.0); cli=d2.number_input('Client Target',0,int(act.get('Clients',0))); ncli=d3.number_input('New Client Target',0,int(act.get('New Clients',0))); scen=d3.selectbox('Final Scenario',['Conservative','Target','Stretch'],index=1); note=d3.text_area('Target Notes'); go=st.form_submit_button('SUBMIT FINAL TARGET',type='primary')
 if go:
  row=save(partner,{'review_date':rd,'target_month':tm,'sales':sal,'sip':sip,'aum':aum,'clients':cli,'new_clients':ncli},scen,{**base,'notes':note,'formula_status':'ILLUSTRATIVE'},u['Email']); st.success(f"Target saved centrally: {row['Target ID']} | Version {row['Version']}"); ep=excel(row); pp=pdf(partner,row,ssn[scen]); st.download_button('Download Target Excel',open(ep,'rb'),file_name=ep.name); st.download_button('Download Review PDF',open(pp,'rb'),file_name=pp.name)
 st.markdown('<div class="section">6. Review / Shortfall Capture</div>',unsafe_allow_html=True)
 with st.form('review'):
  rd2=st.date_input('Review Date',date.today(),key='rd2'); reason=st.text_area('Reason for Shortfall'); problems=st.text_area('Problems Discussed'); approach=st.text_area('Approach / Way Forward'); nextd=st.date_input('Next Review Date',date.today()); owner=st.text_input('Owner',u['Name']); comments=st.text_area('Comments'); saveit=st.form_submit_button('SAVE REVIEW')
 if saveit:
  tt=latest_target(pid) or {}; aa=latest_actual(pid) or {}; rows=pd.DataFrame([{'Review ID':f"REV-{pd.Timestamp.now():%Y%m%d%H%M%S}",'Partner ID':pid,'Review Date':rd2,'Target ID':tt.get('Target ID',''),'RM':partner['RM'],'Branch':partner['Branch'],'Cluster':partner['Cluster'],'Reason for Shortfall':reason,'Problems Discussed':problems,'Approach / Way Forward':approach,'Next Review Date':nextd,'Owner':owner,'Comments':comments,'Created Timestamp':pd.Timestamp.now(),'Created By':u['Email']}]); append_excel(rows,REVIEW_HISTORY); st.success('Review saved.')
with tabs[1]:
 st.subheader('Target vs Actual'); ids=sorted(set(t['Partner ID'].astype(str))&set(p['Partner ID'].astype(str))) if not t.empty else []; 
 if ids:
  pid2=st.selectbox('Performance Partner',ids); c=compare(latest_target(pid2),latest_actual(pid2)); st.dataframe(c.assign(Target=c.Target.map(money),Actual=c.Actual.map(money),Gap=c.Gap.map(money),**{'Achievement %':c['Achievement %'].map(lambda z:f'{z:.1f}%')}),use_container_width=True,hide_index=True); st.plotly_chart(px.bar(c,x='KPI',y='Achievement %',title='Achievement %'),use_container_width=True)
 else: st.info('No finalized targets available.')
with tabs[2]:
 ar=r[r['Partner ID'].astype(str).isin(p['Partner ID'].astype(str))] if not r.empty else r; st.dataframe(ar,use_container_width=True,hide_index=True) if not ar.empty else st.info('No review history available.')
with tabs[3]:
 if u.get('Role')!='Admin': st.warning('Admin controls are restricted.')
 else:
  c=st.columns(4); c[0].metric('Partners',len(partners())); c[1].metric('Actual rows',len(a)); c[2].metric('Final targets',len(t)); c[3].metric('Reviews',len(r)); st.dataframe(__import__('services.data_access',fromlist=['users']).users(),use_container_width=True,hide_index=True)
