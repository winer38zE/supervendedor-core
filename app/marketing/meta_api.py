from facebook_business.api import FacebookAdsApi
from dotenv import load_dotenv
load_dotenv() # <--- ¡Esto es lo que hace que Python vea el archivo .env!from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.campaign import Campaign
import os

class MetaAdsManager:
    def __init__(self):
        # Cargamos y limpiamos las variables de entorno
        self.access_token = os.environ.get("META_ACCESS_TOKEN", "").strip()
        self.ad_account_id = os.environ.get("META_AD_ACCOUNT_ID", "").strip()
        
        # DEBUG
        print(f"DEBUG: Token cargado? {bool(self.access_token)}")
        print(f"DEBUG: ID de cuenta: {self.ad_account_id}")

        if not self.ad_account_id:
            raise ValueError("¡Falta el ID de la cuenta publicitaria en el .env!")
        if not self.access_token:
            raise ValueError("¡Falta el META_ACCESS_TOKEN en el .env!")

        # Inicialización de la API
        FacebookAdsApi.init(access_token=self.access_token)
        
        # Manejo correcto del ID
        account_id = self.ad_account_id if self.ad_account_id.startswith('act_') else f'act_{self.ad_account_id}'
        self.account = AdAccount(account_id)

    def get_account_metrics(self):
        """Obtiene el rendimiento actual de tu cuenta."""
        params = {
            'time_range': {'since': '2026-01-01', 'until': '2026-12-31'},
            'level': 'account',
        }
        fields = ['spend', 'impressions', 'clicks', 'ctr', 'cpc']
        return self.account.get_insights(fields=fields, params=params)

    def pausar_campana(self, campaign_id: str):
        """Pausa una campaña específica."""
        campaign = Campaign(campaign_id)
        return campaign.api_update(params={'status': 'PAUSED'})