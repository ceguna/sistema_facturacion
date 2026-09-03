from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import generic
from django.contrib.messages.views import SuccessMessageMixin

from bases.views import SinPrivilegios

from .models import Empresa, Sucursal, PuntoVenta
from .forms import EmpresaForm, SucursalForm, PuntoVentaForm
from .services import registrar_punto_venta_sin, EmisionSinError


class EmpresaConfigView(SuccessMessageMixin, SinPrivilegios, generic.UpdateView):
    """
    Configuracion de la empresa emisora (fila unica). Si todavia no
    existe ninguna fila (instalacion nueva) se crea una vacia para
    poder editarla, en vez de exigir un flujo de "crear" aparte.
    """
    permission_required = "fe.change_empresa"
    model = Empresa
    form_class = EmpresaForm
    template_name = "fe/empresa_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("fe:empresa_config")
    success_message = "Configuración de la empresa actualizada satisfactoriamente"

    def get_object(self, queryset=None):
        obj = Empresa.objects.first()
        if not obj:
            obj = Empresa.objects.create(razon_social="")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sucursales"] = self.object.sucursales.all().order_by("codigo_sucursal")
        return context


class SucursalNew(SuccessMessageMixin, SinPrivilegios, generic.CreateView):
    permission_required = "fe.add_sucursal"
    model = Sucursal
    form_class = SucursalForm
    template_name = "fe/sucursal_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("fe:empresa_config")
    success_message = "Sucursal agregada satisfactoriamente"

    def form_valid(self, form):
        empresa = Empresa.objects.first()
        if not empresa:
            empresa = Empresa.objects.create(razon_social="")
        form.instance.empresa = empresa
        return super().form_valid(form)


class SucursalEdit(SuccessMessageMixin, SinPrivilegios, generic.UpdateView):
    permission_required = "fe.change_sucursal"
    model = Sucursal
    form_class = SucursalForm
    template_name = "fe/sucursal_form.html"
    context_object_name = "obj"
    success_url = reverse_lazy("fe:empresa_config")
    success_message = "Sucursal actualizada satisfactoriamente"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["puntos_venta"] = self.object.puntos_venta.all().order_by("codigo_punto_venta")
        return context


class SucursalDel(SinPrivilegios, generic.DeleteView):
    permission_required = "fe.delete_sucursal"
    model = Sucursal
    template_name = "fe/sucursal_del.html"
    context_object_name = "obj"
    success_url = reverse_lazy("fe:empresa_config")


class PuntoVentaNew(SuccessMessageMixin, SinPrivilegios, generic.CreateView):
    permission_required = "fe.add_puntoventa"
    model = PuntoVenta
    form_class = PuntoVentaForm
    template_name = "fe/puntoventa_form.html"
    context_object_name = "obj"
    success_message = "Punto de venta registrado ante el SIN satisfactoriamente"

    def dispatch(self, request, *args, **kwargs):
        self.sucursal = get_object_or_404(Sucursal, pk=kwargs["sucursal_id"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # El codigo_punto_venta NO se pone a mano -- se consigue del
        # SIN antes de guardar nada. Si el SIN lo rechaza, no se crea
        # ningun registro local a medias (mismo principio que ya
        # aplicamos en facturas: nunca dejar un registro huerfano si
        # una validacion externa puede fallar).
        try:
            codigo_asignado = registrar_punto_venta_sin(
                sucursal=self.sucursal,
                nombre_punto_venta=form.cleaned_data['nombre'],
                descripcion=form.cleaned_data['descripcion'],
                codigo_tipo_punto_venta=form.cleaned_data['codigo_tipo_punto_venta'],
            )
        except EmisionSinError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        form.instance.sucursal = self.sucursal
        form.instance.codigo_punto_venta = codigo_asignado
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sucursal"] = self.sucursal
        return context

    def get_success_url(self):
        return reverse_lazy("fe:sucursal_edit", kwargs={"pk": self.sucursal.id})


class PuntoVentaEdit(SuccessMessageMixin, SinPrivilegios, generic.UpdateView):
    """
    Solo permite editar nombre/descripcion/tipo localmente -- NO
    vuelve a llamar a registroPuntoVenta (ya se registro una vez al
    crearlo; volver a registrar el mismo punto de venta no tiene
    sentido y probablemente el SIN lo rechace o cree uno duplicado).
    codigo_punto_venta no forma parte de PuntoVentaForm, asi que queda
    intacto sin hacer nada especial aca.
    """
    permission_required = "fe.change_puntoventa"
    model = PuntoVenta
    form_class = PuntoVentaForm
    template_name = "fe/puntoventa_form.html"
    context_object_name = "obj"
    success_message = "Punto de venta actualizado satisfactoriamente"

    def get_success_url(self):
        return reverse_lazy("fe:sucursal_edit", kwargs={"pk": self.object.sucursal.id})


class PuntoVentaDel(SinPrivilegios, generic.DeleteView):
    permission_required = "fe.delete_puntoventa"
    model = PuntoVenta
    template_name = "fe/puntoventa_del.html"
    context_object_name = "obj"

    def get_success_url(self):
        return reverse_lazy("fe:sucursal_edit", kwargs={"pk": self.object.sucursal.id})
