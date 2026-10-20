
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
