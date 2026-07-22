from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import generic
from django.contrib.messages.views import SuccessMessageMixin

from bases.views import SinPrivilegios

from .models import Empresa, Sucursal, PuntoVenta
from .forms import EmpresaForm, SucursalForm, PuntoVentaForm


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
    success_message = "Punto de venta agregado satisfactoriamente"

    def dispatch(self, request, *args, **kwargs):
        self.sucursal = get_object_or_404(Sucursal, pk=kwargs["sucursal_id"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.sucursal = self.sucursal
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sucursal"] = self.sucursal
        return context

    def get_success_url(self):
        return reverse_lazy("fe:sucursal_edit", kwargs={"pk": self.sucursal.id})


class PuntoVentaEdit(SuccessMessageMixin, SinPrivilegios, generic.UpdateView):
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
