"""
Alcance por sucursal (24/09/2026, pedido de Carlos): que sucursal(es)
puede VER cada usuario en listados, reportes, dashboard, etc.

Distinto de obtener_sucursal_actual() (bases/views.py), que resuelve en
que sucursal OPERA/registra el usuario. Esto solo limita lo que se ve:
  - Superusuario, sin PerfilUsuario, o PerfilUsuario.alcance='TODAS'
    -> ve todas las sucursales (comportamiento de siempre).
  - alcance='SUCURSAL' -> solo su sucursal asignada. Si eligio ese
    alcance pero no tiene sucursal, no ve nada (falla cerrado, nunca
    abierto).
"""
from django.db.models import Q


def sucursales_visibles_ids(user):
    """None = sin restriccion (todas). Lista de ids = solo esas."""
    if not user.is_authenticated or user.is_superuser:
        return None
    perfil = getattr(user, 'perfilusuario', None)
    if not perfil or perfil.alcance != 'SUCURSAL':
        return None
    return [perfil.sucursal_id] if perfil.sucursal_id else []


def puede_ver_sucursal(user, sucursal_id):
    ids = sucursales_visibles_ids(user)
    return ids is None or sucursal_id in ids


def sucursal_elegida(request):
    """Sucursal elegida en el filtro de pantalla (?sucursal=N), o None."""
    valor = (request.GET.get('sucursal') or '').strip()
    return int(valor) if valor.isdigit() else None


def q_alcance(user, *campos):
    """Q que limita a las sucursales visibles del usuario en cualquiera
    de los campos dados (ej. origen/destino de una transferencia)."""
    ids = sucursales_visibles_ids(user)
    if ids is None:
        return Q()
    q = Q(pk__in=[])
    for campo in campos:
        q |= Q(**{campo + '__in': ids})
    return q


def filtrar_por_sucursal(qs, request, campo='sucursal', usar_filtro_pantalla=True):
    """Aplica el alcance del usuario y, si corresponde, el filtro
    ?sucursal=N elegido en pantalla (siempre dentro del alcance)."""
    ids = sucursales_visibles_ids(request.user)
    if ids is not None:
        qs = qs.filter(**{campo + '__in': ids})
    elegida = sucursal_elegida(request) if usar_filtro_pantalla else None
    if elegida:
        qs = qs.filter(**{campo: elegida})
    return qs


def contexto_filtro_sucursal(request):
    """Datos para el selector de sucursal de las pantallas de listado.
    El selector solo aparece si el usuario puede ver 2+ sucursales."""
    from fe.models import Sucursal
    sucursales = Sucursal.objects.all().order_by('codigo_sucursal')
    ids = sucursales_visibles_ids(request.user)
    if ids is not None:
        sucursales = sucursales.filter(pk__in=ids)
    lista = list(sucursales)
    return {
        'sucursales_filtro': lista if len(lista) > 1 else [],
        'sucursal_sel': sucursal_elegida(request),
    }


def mapa_stock(request, usar_filtro_pantalla=True):
    """
    {producto_id: cantidad} sumando StockSucursal SOLO de las
    sucursales que el usuario puede ver (y la elegida en pantalla, si
    hay). Devuelve None si no hay ninguna restriccion ni filtro -- en
    ese caso se usa Producto.existencia (el total agregado), que es
    identico y no cuesta una consulta extra.
    """
    from django.db.models import Sum
    from inv.models import StockSucursal
    ids = sucursales_visibles_ids(request.user)
    elegida = sucursal_elegida(request) if usar_filtro_pantalla else None
    if ids is None and not elegida:
        return None
    qs = StockSucursal.objects.all()
    if ids is not None:
        qs = qs.filter(sucursal_id__in=ids)
    if elegida:
        qs = qs.filter(sucursal_id=elegida)
    return {r['producto_id']: r['t'] for r in qs.values('producto_id').annotate(t=Sum('cantidad'))}


def existencia_de(producto, mapa):
    return producto.existencia if mapa is None else mapa.get(producto.id, 0)


# ---------------------------------------------------------------------
# Guardia a nivel de OBJETO: un usuario limitado a su sucursal no debe
# poder abrir/operar un documento de otra sucursal escribiendo su ID en
# la URL (el filtro de los listados solo oculta, no protege).
# ---------------------------------------------------------------------
from functools import wraps


def _sucursales_de(modelo_path, campos, pk):
    """Devuelve None si el objeto no existe, o la lista de ids de
    sucursal (pueden ser None) de los campos indicados."""
    from django.apps import apps
    Modelo = apps.get_model(modelo_path)
    fila = Modelo.objects.filter(pk=pk).values_list(*campos).first()
    return None if fila is None else list(fila)


def objeto_visible(user, modelo_path, campos, pk):
    ids = sucursales_visibles_ids(user)
    if ids is None:
        return True
    suc = _sucursales_de(modelo_path, campos, pk)
    if suc is None:
        return True  # no existe: que la vista responda su 'no existe' de siempre
    return any(s in ids for s in suc if s is not None)


def requiere_alcance(modelo_path, campos=('sucursal_id',), kwarg='id'):
    """Decorador de vistas funcion: si el objeto (pk en kwargs[kwarg])
    es de una sucursal fuera del alcance del usuario, redirige a
    'sin privilegios'. Va DEBAJO de login_required/permission_required."""
    def deco(view):
        @wraps(view)
        def envuelta(request, *args, **kwargs):
            pk = kwargs.get(kwarg)
            if pk is not None and not objeto_visible(request.user, modelo_path, campos, pk):
                from django.shortcuts import redirect
                return redirect('bases:sin_privilegios')
            return view(request, *args, **kwargs)
        return envuelta
    return deco


class AlcanceObjetoMixin:
    """Para vistas basadas en clase: valida kwargs[alcance_kwarg] contra
    el alcance del usuario antes de despachar."""
    alcance_modelo = None
    alcance_campos = ('sucursal_id',)
    alcance_kwarg = 'id'

    def dispatch(self, request, *args, **kwargs):
        pk = kwargs.get(self.alcance_kwarg)
        if pk is not None and not objeto_visible(request.user, self.alcance_modelo, self.alcance_campos, pk):
            from django.shortcuts import redirect
            return redirect('bases:sin_privilegios')
        return super().dispatch(request, *args, **kwargs)
