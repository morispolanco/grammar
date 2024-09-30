import streamlit as st
import stripe
import os
from io import BytesIO
import docx
import requests
import jwt
import datetime
from docx.oxml.ns import qn

# Set full-width layout
st.set_page_config(layout="wide")

# Configurar la clave secreta de Stripe desde Streamlit Secrets
stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]  # Acceder a Stripe secret desde Streamlit secrets

# ID del producto para Stripe (reemplazar con tu ID de producto)
PRODUCT_ID = "prod_Qw7Ye65kBkYZas"  # Reemplazar con tu Stripe product ID

# Obtener JWT_SECRET desde Streamlit secrets
JWT_SECRET = st.secrets["JWT_SECRET"]

# Función para generar un JWT para el success_url
def generate_jwt_token():
    payload = {
        "url": "https://correctorgramatical.streamlit.app/?success=true",
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=30)  # Expiración del token (30 minutos)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return token

# Función para obtener el precio del producto
def get_price_for_product(product_id):
    try:
        prices = stripe.Price.list(product=product_id)
        if prices and prices['data']:
            return prices['data'][0].id
        else:
            st.error("No se encontraron precios para el producto.")
            return None
    except Exception as e:
        st.error(f"Error al obtener el precio: {e}")
        return None

# Función para crear una sesión de pago con Stripe
def create_checkout_session(price_id):
    try:
        token = generate_jwt_token()  # Generar el token JWT para el success URL
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"https://correctorgramatical.streamlit.app/?token={token}",  # Usar el token JWT en el success URL
            cancel_url="https://correctorgramatical.streamlit.app/?cancel=true",
        )
        return session
    except Exception as e:
        st.error(f"Error al crear la sesión de pago: {e}")
        return None

# Función para conectar con la API de LanguageTool y aplicar correcciones
def correct_text_with_languagetool(text, language):
    languagetool_url = "https://api.languagetool.org/v2/check"
    language_codes = {
        "en": "en-US", "es": "es", "fr": "fr", "de": "de", "pt": "pt"
    }

    params = {
        'text': text,
        'language': language_codes.get(language, "en-US"),
        'level': 'picky',  # Usar el nivel "picky" para aplicar más correcciones
        'enabledCategories': 'grammar,style,typos',  # Habilitar correcciones gramaticales, de estilo y tipográficas
        'enabledRules': 'WHITESPACE_RULE,EN_UNPAIRED_BRACKETS,UPPERCASE_SENTENCE_START,WORDINESS,REDUNDANCY,MISSING_COMMA,COMMA_PARENTHESIS_WHITESPACE,DASH_RULE,EN_QUOTES,AGREEMENT_SENT_START,SENTENCE_FRAGMENT,MULTIPLICATION_SIGN,PASSIVE_VOICE,EXTRA_WHITESPACE,COMMA_BEFORE_CONJUNCTION,HYPHENATION_RULES,ITS_IT_IS,DUPLICATE_WORD,NO_SPACE_BEFORE_PUNCTUATION',  # Más reglas de estilo y claridad
        'disabledCategories': 'COLLOQUIALISMS'  # Deshabilitar lenguaje coloquial para precisión científica
    }

    try:
        response = requests.post(languagetool_url, data=params)
        if response.status_code == 200:
            matches = response.json().get('matches', [])
            corrected_text = apply_corrections(text, matches)
            return corrected_text
        else:
            st.error("Error en la respuesta de la API de LanguageTool.")
            return text
    except requests.exceptions.RequestException as e:
        st.error(f"Error en la solicitud de la API: {e}")
        return text

# Función para aplicar correcciones al texto
def apply_corrections(text, matches):
    corrections = []
    for match in matches:
        if match['replacements']:
            replacement = match['replacements'][0]['value']
            start_pos = match['offset']
            end_pos = start_pos + match['length']
            corrections.append((start_pos, end_pos, replacement))

    corrected_text = text
    offset = 0
    for start_pos, end_pos, replacement in sorted(corrections):
        corrected_text = corrected_text[:start_pos + offset] + replacement + corrected_text[end_pos + offset:]
        offset += len(replacement) - (end_pos - start_pos)
    return corrected_text

# Función para manejar el procesamiento de un párrafo
def process_paragraph(paragraph, language):
    if paragraph_contains_footnote_reference(paragraph):
        return  # Omitir párrafos con notas al pie

    full_text = "".join([run.text for run in paragraph.runs])
    corrected_paragraph_text = correct_text_with_languagetool(full_text, language)
    apply_corrected_text_to_runs(paragraph, corrected_paragraph_text)

# Función para verificar si un párrafo contiene una referencia de nota al pie
def paragraph_contains_footnote_reference(paragraph):
    for run in paragraph.runs:
        for child in run._r:
            if child.tag == qn('w:footnoteReference'):
                return True
    return False

# Función para aplicar el texto corregido a las runs de un párrafo
def apply_corrected_text_to_runs(paragraph, corrected_text):
    current_index = 0
    for run in paragraph.runs:
        text_length = len(run.text)
        run.text = corrected_text[current_index:current_index + text_length]
        current_index += text_length

# Función para verificar el token JWT desde la URL
def verify_jwt_token(token):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("url") == "https://correctorgramatical.streamlit.app/?success=true":
            return True
        return False
    except jwt.ExpiredSignatureError:
        st.error("El token ha expirado.")
        return False
    except jwt.InvalidTokenError:
        st.error("Token inválido.")
        return False

# Función principal de la aplicación Streamlit
def main():
    # Barra lateral con instrucciones y configuración de pago con Stripe
    with st.sidebar:
        st.header("Instrucciones")
        st.markdown("""
        **Esta aplicación te permite:**
        
        - Subir un documento DOCX.
        - Aplicar correcciones ortográficas y gramaticales al texto, excluyendo citas y nombres propios.
        - Preservar las notas al pie.
        
        **Idiomas soportados:**
        
        La aplicación puede corregir documentos en **Inglés, Español, Francés, Italiano, Alemán y Portugués**.
        
        **Longitud del documento:**
        
        - La aplicación tiene virtualmente sin límites en la longitud del documento.
        - Sin embargo, cuanto más largo sea el documento, más tiempo tomará procesarlo.
        - Por ejemplo, un documento de 100 páginas puede tardar hasta 10 minutos en procesarse.
        
        **Control de cambios:**
        
        Para enviar el documento con control de cambios, sigue estos pasos:
        
        1. **Abre Word** y ve a la pestaña **Revisar**.
        2. Usa la opción **Comparar Documentos** y selecciona:
            - El documento original que subiste.
            - El documento corregido descargado desde esta aplicación.
        3. Word mostrará el documento con control de cambios, donde puedes:
            - Aceptar o rechazar las correcciones propuestas.
        4. Guarda el documento con control de cambios y envíalo para su revisión.
        
        **Precio:**
        
        - Se cobra una tarifa fija de 4 USD por documento, independientemente de su longitud.
        
        **Descargo de responsabilidad:**
        
        Es responsabilidad del editor verificar todos los cambios antes de enviar el documento a su destinatario final.
        
        **Autor:** Dr. Moris Polanco (mp @ ufm.edu)
        """)

    # Columna principal para el contenido interactivo
    col_main, _ = st.columns([3, 1])  # Ajuste para centrar el contenido principal

    with col_main:
        st.title("Corrección Ortográfica y Gramatical de Documentos DOCX con Preservación de Notas al Pie")

        # Obtener parámetros de la URL
        success = st.experimental_get_query_params().get("token")
        if success:
            token = success[0]  # Obtener el token de la URL
            if verify_jwt_token(token):
                st.success("¡Pago completado! Ahora puedes subir y procesar tu documento.")
            else:
                st.error("Token inválido. Por favor, completa el pago nuevamente.")
        else:
            st.warning("Debes completar el pago antes de usar la aplicación.")

            # 1. Incluir un ícono o botón más visible para iniciar el pago con Stripe
            # Utilizamos una imagen de "Pay with Stripe" que redirige al usuario al enlace de pago
            pay_button_html = """
                <a href="{url}">
                    <img src="https://upload.wikimedia.org/wikipedia/commons/5/53/Stripe_Logo%2C_revised_2016.svg" alt="Pay with Stripe" width="200">
                </a>
            """
            price_id = get_price_for_product(PRODUCT_ID)
            if price_id:
                session = create_checkout_session(price_id)
                if session:
                    # Renderizar el botón con la imagen y el enlace de pago
                    st.markdown(pay_button_html.format(url=session.url), unsafe_allow_html=True)

        # 2. Permitir la carga de archivos y selección de idioma solo después del pago
        if success and verify_jwt_token(success[0]):
            language = st.selectbox("Selecciona el idioma del documento", ["en", "es", "fr", "de", "pt"])

            uploaded_file = st.file_uploader("Sube un archivo DOCX", type="docx")

            if uploaded_file is not None:
                try:
                    # Intentar abrir el archivo para verificar que es un DOCX válido
                    document = docx.Document(uploaded_file)
                except Exception as e:
                    st.error("El archivo subido no es un DOCX válido o está dañado.")
                else:
                    if st.button("Enviar"):
                        try:
                            progress_bar = st.progress(0)
                            total_paragraphs = len(document.paragraphs)

                            for i, paragraph in enumerate(document.paragraphs):
                                process_paragraph(paragraph, language)
                                progress_bar.progress((i + 1) / total_paragraphs)

                            corrected_file = BytesIO()
                            document.save(corrected_file)
                            corrected_file.seek(0)

                            st.download_button(
                                label="Descargar documento corregido",
                                data=corrected_file,
                                file_name="documento_corregido.docx",
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            )

                            st.success("¡Documento procesado y descargado exitosamente!")
                        except Exception as e:
                            st.error(f"Ocurrió un error al procesar el documento: {e}")
                        finally:
                            # Eliminar el flag de éxito y regresar al estado original
                            st.experimental_set_query_params()  # Esto borra todos los parámetros de consulta

if __name__ == "__main__":
    main()
