import requests

def validar_cedula_ecuador(cedula):
    """ Valida matemáticamente la cédula (Módulo 10) """
    if len(cedula) != 10 or not cedula.isdigit():
        return False
    try:
        provincia = int(cedula[0:2])
        if provincia < 1 or provincia > 24: return False
        
        coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
        total = sum([
            (int(cedula[i]) * coeficientes[i] if int(cedula[i]) * coeficientes[i] < 10 
             else int(cedula[i]) * coeficientes[i] - 9) 
            for i in range(9)
        ])
        digito = int(cedula[9])
        calculado = (total + 9) // 10 * 10 - total
        if calculado == 10: calculado = 0
        return calculado == digito
    except:
        return False

def consultar_sri(cedula):
    """
    Intenta obtener el nombre, pero si falla, no rompe el sistema.
    """
    ruc = f"{cedula}001"
    url = f"https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest/Ruc/recuperarDatosRuc?numeroRuc={ruc}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        # Timeout corto (2s) para no hacer esperar al usuario si el SRI está lento
        response = requests.get(url, headers=headers, timeout=2)
        
        if response.status_code == 200:
            datos = response.json()
            nombre = datos.get('razonSocial')
            if nombre:
                return nombre.title()
    except:
        # Si falla (Error 400, Sin internet, etc.), simplemente retornamos None
        # y dejamos que el usuario escriba.
        pass

    return None