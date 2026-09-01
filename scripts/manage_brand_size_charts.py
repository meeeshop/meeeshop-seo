import sys, os, requests, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secrets_manager import get_secret

store = get_secret('SHOPIFY_STORE')
token = get_secret('SHOPIFY_ACCESS_TOKEN')
live_theme_id = "158183882923"
headers = {'X-Shopify-Access-Token': token, 'Content-Type': 'application/json'}

def put_asset(theme_id, key, value):
    url = f"https://{store}/admin/api/2024-10/themes/{theme_id}/assets.json"
    payload = {"asset": {"key": key, "value": value}}
    resp = requests.put(url, headers=headers, json=payload)
    return resp.status_code in (200, 201)

def sync_brand_size_charts():
    """
    Ensures all brand size charts, theme templates, and centered product modal popups are synced.
    """
    print("=== SYNCING BRAND SIZE CHARTS & THEME MODAL ===")
    
    # 1. Ensure Brand Size Chart Snippet exists with Centered Modal Overlay
    snippet_content = """{%- comment -%}
  Dynamic Brand Size Chart Popup Modal Snippet - Centered Viewport Overlay
{%- endcomment -%}

{%- liquid
  assign vendor_handle = product.vendor | handleize
  assign title_lower = product.title | downcase
  assign size_chart_url = ''
  assign size_chart_name = ''

  if vendor_handle contains 'ymi' or title_lower contains 'ymi'
    assign size_chart_url = '/pages/ymi-jeans-size-chart'
    assign size_chart_name = 'YMI Jeans Size Guide'
  elsif vendor_handle contains 'judy' or title_lower contains 'judy blue'
    assign size_chart_url = '/pages/judy-blue-size-chart'
    assign size_chart_name = 'Judy Blue Sizing & Stretch Guide'
  elsif vendor_handle contains 'risen' or title_lower contains 'risen'
    assign size_chart_url = '/pages/risen-jeans-size-chart'
    assign size_chart_name = 'Risen Jeans Fit Guide'
  elsif vendor_handle contains 'artemis' or title_lower contains 'artemis'
    assign size_chart_url = '/pages/artemis-vintage-size-chart'
    assign size_chart_name = 'Artemis Vintage Size Chart'
  elsif vendor_handle contains 'hyfve' or title_lower contains 'hyfve'
    assign size_chart_url = '/pages/hyfve-sizing-chart'
    assign size_chart_name = 'HYFVE Sizing Chart'
  elsif vendor_handle contains 'orange-farm' or title_lower contains 'orange farm'
    assign size_chart_url = '/pages/orange-farm-clothing-sizing-chart'
    assign size_chart_name = 'Orange Farm Size Chart'
  elsif vendor_handle contains 'zenana' or title_lower contains 'zenana'
    assign size_chart_url = '/pages/zenana-womens-clothing-size-chart'
    assign size_chart_name = 'ZENANA Sizing Chart'
  elsif vendor_handle contains 'joanie' or title_lower contains 'hey joanie'
    assign size_chart_url = '/pages/hey-joanie-size-chart'
    assign size_chart_name = 'Hey Joanie Sizing Guide'
  elsif vendor_handle contains 'emory' or title_lower contains 'emory park'
    assign size_chart_url = '/pages/emory-park-sizing-chart'
    assign size_chart_name = 'Emory Park Size Guide'
  elsif vendor_handle contains 'bibi' or title_lower contains 'bibi'
    assign size_chart_url = '/pages/bibi-sizing-chart'
    assign size_chart_name = 'BiBi Sizing Guide'
  elsif vendor_handle contains 'monkey' or vendor_handle contains 'vervet' or title_lower contains 'flying monkey' or title_lower contains 'vervet'
    assign size_chart_url = '/pages/flying-monkey-sizing-chart'
    assign size_chart_name = 'Flying Monkey / Vervet Size Chart'
  elsif vendor_handle contains 'kancan' or title_lower contains 'kancan'
    assign size_chart_url = '/pages/kancan-usa-sizing-chart'
    assign size_chart_name = 'KANCAN USA Size Chart'
  elsif vendor_handle contains 'heyson' or title_lower contains 'heyson'
    assign size_chart_url = '/pages/heyson-sizing-chart'
    assign size_chart_name = 'Heyson Sizing Guide'
  elsif vendor_handle contains 'jade' or title_lower contains 'jade by jane'
    assign size_chart_url = '/pages/jade-by-jane-clothing-size-chart'
    assign size_chart_name = 'Jade By Jane Size Chart'
  elsif vendor_handle contains 'davi' or title_lower contains 'davi & dani'
    assign size_chart_url = '/pages/davi-dani-sizing-chart'
    assign size_chart_name = 'Davi & Dani Sizing Guide'
  elsif vendor_handle contains 'gilli' or title_lower contains 'gilli'
    assign size_chart_url = '/pages/gilli-sizing-chart'
    assign size_chart_name = 'Gilli Size Chart'
  elsif vendor_handle contains 'vibrant' or title_lower contains 'vibrant miu'
    assign size_chart_url = '/pages/vibrant-miu-sizing-chart'
    assign size_chart_name = 'Vibrant M.i.U Size Chart'
  elsif vendor_handle contains 'mono' or title_lower contains 'mono b'
    assign size_chart_url = '/pages/mono-b-clothing-sizing-chart'
    assign size_chart_name = 'Mono B Size Chart'
  elsif product.type contains 'Shoe' or product.type contains 'Footwear' or product.type contains 'Sandals'
    assign size_chart_url = '/pages/shoe-sizing-chart'
    assign size_chart_name = 'Footwear Size Chart'
  elsif product.type contains 'Dress' or product.type contains 'Jeans' or product.type contains 'Pant' or product.type contains 'Top' or product.type contains 'Shirt' or product.type contains 'Sweater'
    assign size_chart_url = '/pages/size-guide'
    assign size_chart_name = 'Standard Size Guide'
  endif
-%}

{%- if size_chart_url != blank -%}
  <div class="product-size-chart-trigger" style="margin: 8px 0 14px 0;">
    <button 
      type="button" 
      id="open-size-chart-modal-btn"
      aria-haspopup="dialog"
      style="display: inline-flex; align-items: center; gap: 6px; background: none; border: none; padding: 0; cursor: pointer; color: #111827; font-size: 1.35rem; font-family: inherit;"
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4b5563" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0;">
        <path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.4 2.4 0 0 1 0-3.4l2.6-2.6a2.4 2.4 0 0 1 3.4 0l12.6 12.6z"></path>
        <path d="m14.5 5.5 1 1"></path>
        <path d="m11.5 8.5 2 2"></path>
        <path d="m8.5 11.5 1 1"></path>
        <path d="m5.5 14.5 2 2"></path>
      </svg>
      <span style="font-weight: 600; text-decoration: underline; text-underline-offset: 3px; color: #1f2937;">
        {{ size_chart_name }}
      </span>
    </button>
  </div>

  <div 
    id="size-chart-modal" 
    role="dialog" 
    aria-modal="true" 
    aria-hidden="true" 
    style="display: none; position: fixed !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; width: 100vw !important; height: 100vh !important; z-index: 2147483647 !important; margin: 0 !important; padding: 16px !important; box-sizing: border-box !important;"
  >
    <div 
      id="size-chart-modal-backdrop" 
      style="position: fixed !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; width: 100% !important; height: 100% !important; background: rgba(0, 0, 0, 0.65) !important; backdrop-filter: blur(4px) !important; -webkit-backdrop-filter: blur(4px) !important;"
    ></div>
    
    <div 
      id="size-chart-modal-dialog"
      style="position: relative !important; margin: auto !important; background: #ffffff !important; width: 100% !important; max-width: 760px !important; max-height: 86vh !important; border-radius: 12px !important; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.45) !important; display: flex !important; flex-direction: column !important; z-index: 10 !important; overflow: hidden !important; animation: scModalCenterFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;"
    >
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 1.2rem 1.8rem; border-bottom: 1px solid #e5e7eb; background: #f9fafb;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#111827" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.4 2.4 0 0 1 0-3.4l2.6-2.6a2.4 2.4 0 0 1 3.4 0l12.6 12.6z"></path>
          </svg>
          <h3 style="margin: 0; font-size: 1.6rem; font-weight: 700; color: #111827;">{{ size_chart_name }}</h3>
        </div>
        <button type="button" id="close-size-chart-modal-btn" aria-label="Close size guide" style="background: none; border: none; font-size: 2.2rem; cursor: pointer; color: #4b5563; line-height: 1; padding: 4px 10px; border-radius: 6px;">&times;</button>
      </div>

      <div id="size-chart-modal-body" style="padding: 1.8rem; overflow-y: auto; flex-grow: 1; font-size: 1.4rem; color: #374151; -webkit-overflow-scrolling: touch;">
        <div id="size-chart-loading" style="text-align: center; padding: 3rem 1rem; color: #6b7280;">
          <div style="font-size: 1.5rem; font-weight: 600; margin-bottom: 6px;">Loading measurement chart...</div>
          <div style="font-size: 1.2rem;">Please wait a moment</div>
        </div>
        <div id="size-chart-content" style="display: none;"></div>
      </div>

      <div style="padding: 1rem 1.8rem; border-top: 1px solid #e5e7eb; background: #f9fafb; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
        <span style="font-size: 1.2rem; color: #6b7280;">Need extra help with sizing? Contact support@meeeshop.com</span>
        <button type="button" id="size-chart-done-btn" style="background: #111827; color: #fff; border: none; padding: 9px 22px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 1.3rem;">Close</button>
      </div>
    </div>
  </div>

  <style>
    @keyframes scModalCenterFadeIn {
      from { opacity: 0; transform: scale(0.95); }
      to { opacity: 1; transform: scale(1); }
    }
    #size-chart-content table {
      width: 100% !important;
      border-collapse: collapse !important;
      margin: 1.2rem 0 !important;
      font-size: 1.35rem !important;
    }
    #size-chart-content th, #size-chart-content td {
      border: 1px solid #e2e8f0 !important;
      padding: 10px 14px !important;
      text-align: left !important;
    }
    #size-chart-content th {
      background: #f8fafc !important;
      font-weight: 700 !important;
      color: #1e293b !important;
    }
    #size-chart-content h1, #size-chart-content h2 {
      color: #0f172a !important;
    }
  </style>

  <script>
    (function() {
      const openBtn = document.getElementById('open-size-chart-modal-btn');
      const modal = document.getElementById('size-chart-modal');
      const backdrop = document.getElementById('size-chart-modal-backdrop');
      const closeBtn = document.getElementById('close-size-chart-modal-btn');
      const doneBtn = document.getElementById('size-chart-done-btn');
      const loading = document.getElementById('size-chart-loading');
      const content = document.getElementById('size-chart-content');
      let loaded = false;

      if (modal && modal.parentNode !== document.body) {
        document.body.appendChild(modal);
      }

      function openModal() {
        if (!modal) return;
        modal.style.setProperty('display', 'flex', 'important');
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';

        if (!loaded) {
          fetch('{{ size_chart_url }}')
            .then(res => res.text())
            .then(html => {
              const parser = new DOMParser();
              const doc = parser.parseFromString(html, 'text/html');
              let bodyElement = doc.querySelector('.size-chart-container') || 
                                doc.querySelector('.main-page-content') || 
                                doc.querySelector('.rte') ||
                                doc.querySelector('main');
              
              if (bodyElement) {
                content.innerHTML = bodyElement.innerHTML;
              } else {
                content.innerHTML = '<p>Unable to load size chart content. Please check back shortly.</p>';
              }
              loading.style.display = 'none';
              content.style.display = 'block';
              loaded = true;
            })
            .catch(() => {
              loading.innerHTML = '<p style="color: #ef4444;">Could not load size guide. Please refresh or try again.</p>';
            });
        }
      }

      function closeModal() {
        if (!modal) return;
        modal.style.setProperty('display', 'none', 'important');
        modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
      }

      if (openBtn) openBtn.addEventListener('click', openModal);
      if (closeBtn) closeBtn.addEventListener('click', closeModal);
      if (doneBtn) doneBtn.addEventListener('click', closeModal);
      if (backdrop) backdrop.addEventListener('click', closeModal);

      document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && modal.style.display === 'flex') {
          closeModal();
        }
      });
    })();
  </script>
{%- endif -%}
"""
    put_asset(live_theme_id, "snippets/brand-size-chart-link.liquid", snippet_content)
    print("✓ Deployed snippets/brand-size-chart-link.liquid")

if __name__ == '__main__':
    sync_brand_size_charts()
